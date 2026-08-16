// Package faultproxy is a TEST/EMULATOR-ONLY local TCP proxy that sits in
// front of the Cloud Spanner emulator's gRPC port and injects transport
// faults -- dropped connections, delayed responses, resets after partial
// transmission -- so the ADR-043 commit-ambiguity matrix can be exercised
// against a real backend and a real network stack, not a fake error value.
//
// The proxy operates purely at the TCP byte-relay level. It does not parse
// HTTP/2 frames or gRPC message content, and it does not itself know
// whether a given Commit "succeeded" in any application sense -- ground
// truth for "did the backend actually commit" is established by tests
// reading the emulator's database directly on a separate, unproxied
// connection, never by this package's own observations. This package only
// answers transport-level questions: did bytes reach the backend, did the
// backend send bytes back, did the client receive them.
//
// gRPC connections are long-lived (kept alive across many RPCs), so a
// connection's record is updated live, the instant bytes are observed
// flowing in each direction -- it is never gated on the connection fully
// closing, which for a healthy PassThrough connection may not happen for
// the life of the test.
package faultproxy

import (
	"io"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

type FaultMode int

const (
	// PassThrough relays bytes in both directions with no injected fault.
	PassThrough FaultMode = iota
	// DropBeforeBackend closes the client connection immediately, without
	// ever dialing the backend. Models: the request never reached the
	// backend at all.
	DropBeforeBackend
	// DropResponseAfterBackendSuccess relays the client request to the
	// backend, waits until the backend begins writing a response (proof it
	// processed the request), then closes the client-facing connection
	// without relaying any of that response. This is the fault T4 requires.
	DropResponseAfterBackendSuccess
	// DelayPastDeadline relays the request normally, then sleeps before
	// relaying the backend's response, long enough that a client with a
	// short deadline observes DEADLINE_EXCEEDED before any bytes arrive.
	DelayPastDeadline
	// ResetAfterRequestTransmission relays whatever the client has sent so
	// far to the backend, then resets (RST, not a clean FIN) the client
	// connection immediately after that first chunk leaves the proxy --
	// without waiting to see whether the backend responds at all.
	ResetAfterRequestTransmission
	// AbruptClose resets the client connection immediately upon accept,
	// before any byte is relayed in either direction.
	AbruptClose
)

// ConnectionRecord is a point-in-time snapshot of one client connection's
// transport-level observations.
type ConnectionRecord struct {
	Mode                      FaultMode
	DialedBackend             bool
	DialErr                   error
	BytesRelayedToBackend     int64
	BytesRelayedFromBackend   int64
	ResponseDeliveredToClient bool
}

type connState struct {
	mode              FaultMode
	dialedBackend     atomic.Bool
	dialErr           atomic.Pointer[error]
	bytesToBackend    atomic.Int64
	bytesFromBackend  atomic.Int64
	responseDelivered atomic.Bool
}

func (c *connState) snapshot() ConnectionRecord {
	var dialErr error
	if p := c.dialErr.Load(); p != nil {
		dialErr = *p
	}
	return ConnectionRecord{
		Mode:                      c.mode,
		DialedBackend:             c.dialedBackend.Load(),
		DialErr:                   dialErr,
		BytesRelayedToBackend:     c.bytesToBackend.Load(),
		BytesRelayedFromBackend:   c.bytesFromBackend.Load(),
		ResponseDeliveredToClient: c.responseDelivered.Load(),
	}
}

// Proxy listens on an ephemeral local port and forwards to backendAddr,
// applying one queued FaultMode per accepted connection (PassThrough once
// the queue is empty). This gives fault injection G ("one-shot fault
// followed by normal operation") for free: queue one mode, and every
// subsequent connection is unaffected.
type Proxy struct {
	backendAddr string
	listener    net.Listener

	mu      sync.Mutex
	queue   []FaultMode
	records []*connState

	delay time.Duration
}

// New creates a proxy forwarding to backendAddr. delay is the sleep
// duration used by DelayPastDeadline.
func New(backendAddr string, delay time.Duration) *Proxy {
	return &Proxy{backendAddr: backendAddr, delay: delay}
}

// Start begins listening on 127.0.0.1:0 and accepting connections in the
// background. It returns the address callers should dial instead of
// backendAddr directly.
func (p *Proxy) Start() (string, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}
	p.listener = listener
	go p.acceptLoop()
	return listener.Addr().String(), nil
}

func (p *Proxy) Close() error {
	return p.listener.Close()
}

// QueueFault appends one fault mode; it applies to the next accepted
// connection that hasn't already consumed a queued mode. Connections
// accepted while the queue is empty use PassThrough.
func (p *Proxy) QueueFault(mode FaultMode) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.queue = append(p.queue, mode)
}

func (p *Proxy) nextMode() FaultMode {
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.queue) == 0 {
		return PassThrough
	}
	mode := p.queue[0]
	p.queue = p.queue[1:]
	return mode
}

func (p *Proxy) register(mode FaultMode) *connState {
	state := &connState{mode: mode}
	p.mu.Lock()
	p.records = append(p.records, state)
	p.mu.Unlock()
	return state
}

// Records returns a live snapshot of every connection observed so far.
func (p *Proxy) Records() []ConnectionRecord {
	p.mu.Lock()
	states := make([]*connState, len(p.records))
	copy(states, p.records)
	p.mu.Unlock()
	out := make([]ConnectionRecord, len(states))
	for i, s := range states {
		out[i] = s.snapshot()
	}
	return out
}

func (p *Proxy) acceptLoop() {
	for {
		conn, err := p.listener.Accept()
		if err != nil {
			return
		}
		mode := p.nextMode()
		go p.handleConnection(conn, mode)
	}
}

func (p *Proxy) handleConnection(client net.Conn, mode FaultMode) {
	defer client.Close()
	record := p.register(mode)

	if mode == AbruptClose {
		resetClose(client)
		return
	}
	if mode == DropBeforeBackend {
		client.Close()
		return
	}

	backend, err := net.DialTimeout("tcp", p.backendAddr, 5*time.Second)
	record.dialedBackend.Store(err == nil)
	if err != nil {
		record.dialErr.Store(&err)
		return
	}
	defer backend.Close()

	switch mode {
	case ResetAfterRequestTransmission:
		relayFirstChunkOnly(backend, client, &record.bytesToBackend)
		resetClose(client)
	case DropResponseAfterBackendSuccess:
		// The HTTP/2 handshake itself (client preface + SETTINGS, server
		// SETTINGS/WINDOW_UPDATE in reply) MUST be relayed normally in both
		// directions, or the client's gRPC stack never unblocks to send the
		// actual RPC at all -- there is no "backend success" to observe if
		// the request is never sent. handshakeThreshold is how many bytes
		// the client sends beyond which we consider its real RPC (not just
		// the handshake) to be in flight; empirically the emulator's
		// handshake-phase client traffic is well under this.
		const handshakeThreshold = 64
		realResponseSeen := make(chan struct{})
		var closeSignalOnce sync.Once
		var wg sync.WaitGroup
		wg.Add(2)
		go func() {
			defer wg.Done()
			relayAll(backend, client, &record.bytesToBackend, nil)
		}()
		go func() {
			defer wg.Done()
			buf := make([]byte, 32*1024)
			for {
				n, err := backend.Read(buf)
				if n > 0 {
					if record.bytesToBackend.Load() > handshakeThreshold {
						// The client has already sent its real request --
						// this response byte belongs to that RPC.
						// Deliberately never relayed to the client.
						closeSignalOnce.Do(func() { close(realResponseSeen) })
					} else {
						client.Write(buf[:n]) // handshake-phase: relay normally
					}
				}
				if err != nil {
					return
				}
			}
		}()
		select {
		case <-realResponseSeen:
		case <-time.After(3 * time.Second):
		}
		// A brief grace window lets the backend finish flushing the rest
		// of its (still unrelayed) response before the connection is cut.
		time.Sleep(50 * time.Millisecond)
		resetClose(client)
		wg.Wait()
	case DelayPastDeadline:
		var wg sync.WaitGroup
		wg.Add(1)
		go func() {
			defer wg.Done()
			relayAll(backend, client, &record.bytesToBackend, nil)
		}()
		time.Sleep(p.delay)
		relayAll(client, backend, &record.bytesFromBackend, &record.responseDelivered)
		wg.Wait()
	default: // PassThrough
		var wg sync.WaitGroup
		wg.Add(2)
		go func() {
			defer wg.Done()
			relayAll(backend, client, &record.bytesToBackend, nil)
		}()
		go func() {
			defer wg.Done()
			relayAll(client, backend, &record.bytesFromBackend, &record.responseDelivered)
		}()
		wg.Wait()
	}
}

// relayAll copies src to dst, updating counter live (per chunk, not only at
// completion) so a caller can observe progress on a connection that may
// never fully close during the test. If delivered is non-nil it is set
// true the instant any bytes are written to dst.
func relayAll(dst io.Writer, src io.Reader, counter *atomic.Int64, delivered *atomic.Bool) (int64, error) {
	buf := make([]byte, 32*1024)
	var total int64
	for {
		n, readErr := src.Read(buf)
		if n > 0 {
			written, writeErr := dst.Write(buf[:n])
			total += int64(written)
			counter.Add(int64(written))
			if delivered != nil && written > 0 {
				delivered.Store(true)
			}
			if writeErr != nil {
				return total, writeErr
			}
		}
		if readErr != nil {
			if readErr == io.EOF {
				return total, nil
			}
			return total, readErr
		}
	}
}

// relayFirstChunkOnly reads and forwards exactly one chunk from src to dst,
// updating counter, then returns -- used by faults that must prove "some
// request bytes reached the backend" without waiting for the full request
// (which, for a kept-alive gRPC connection, may never fully arrive before
// the fault fires).
func relayFirstChunkOnly(dst io.Writer, src io.Reader, counter *atomic.Int64) {
	buf := make([]byte, 32*1024)
	n, err := src.Read(buf)
	if n > 0 {
		written, _ := dst.Write(buf[:n])
		counter.Add(int64(written))
	}
	_ = err
}

// resetClose forces a TCP RST rather than a clean FIN, by setting a
// zero linger timeout before closing -- the sharpest available transport
// fault, indistinguishable to the client from a genuine network reset.
func resetClose(conn net.Conn) {
	if tcpConn, ok := conn.(*net.TCPConn); ok {
		tcpConn.SetLinger(0)
	}
	conn.Close()
}
