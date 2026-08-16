//go:build emulator

package spannerprod

import (
	"context"
	"testing"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const emulatorDatabase = "projects/emg-recovery-authority-test/instances/test-instance/databases/test-db"

func TestEmulatorRawCommitPassesThroughToClassifier(t *testing.T) {
	conn, err := grpc.NewClient(
		"localhost:9010",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDisableServiceConfig(),
		grpc.WithDisableRetry(),
	)
	if err != nil {
		t.Fatal(err)
	}
	raw := spannerpb.NewSpannerClient(conn)
	client, err := newClient(raw, conn.Close)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close() })

	ctx := context.Background()
	session, err := raw.CreateSession(ctx, &spannerpb.CreateSessionRequest{
		Database: emulatorDatabase,
		Session:  &spannerpb.Session{},
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		raw.DeleteSession(context.Background(), &spannerpb.DeleteSessionRequest{Name: session.GetName()})
	})
	transaction, err := raw.BeginTransaction(ctx, &spannerpb.BeginTransactionRequest{
		Session: session.GetName(),
		Options: &spannerpb.TransactionOptions{
			Mode: &spannerpb.TransactionOptions_ReadWrite_{
				ReadWrite: &spannerpb.TransactionOptions_ReadWrite{},
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}

	request := &spannerpb.CommitRequest{
		Session: session.GetName(),
		Transaction: &spannerpb.CommitRequest_TransactionId{
			TransactionId: transaction.GetId(),
		},
	}
	response, commitErr := client.Commit(ctx, request)
	classification := rotationcommit.ClassifyCommit(
		true,
		response,
		commitErr,
		rotationcommit.RegularSession,
	)
	if commitErr != nil {
		t.Fatalf("raw Commit error: %v", commitErr)
	}
	if classification.Outcome != protocol.UnambiguousSuccess {
		t.Fatalf("classifier outcome = %v, want UnambiguousSuccess", classification.Outcome)
	}
}
