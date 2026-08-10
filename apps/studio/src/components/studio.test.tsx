import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Studio } from "./studio";
import { I18nProvider } from "@/i18n/i18n";

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderStudio() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<I18nProvider><QueryClientProvider client={client}><Studio /></QueryClientProvider></I18nProvider>);
}

describe("Studio pilot", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("fails closed to the login state when unauthenticated", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ error: "unauthorized" }, 401));
    renderStudio();
    expect(await screen.findByRole("link", { name: /continue to secure sign in/i })).toHaveAttribute(
      "href",
      "/bff/auth/login",
    );
  });

  it("detects an authenticated session and shows the pilot lookup", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ authenticated: true }));
    renderStudio();
    expect(await screen.findByText("Authenticated session")).toBeInTheDocument();
    expect(screen.getByDisplayValue("pilot-entity-001")).toBeInTheDocument();
  });

  it("renders an entity returned by the BFF", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(
        jsonResponse({
          item: {
            summary: { node_id: "pilot-entity-001", node_type: "organization", label: "Pilot Entity", confidence: 0.94, classification: "INTERNAL" },
            source: "pilot-seed", aliases: [], evidence: [], histories: [], metadata: { region: "Dubai" },
          },
          revision_context: { revision_number: 4, committed_at: "2026-01-01T00:00:00Z", is_current_head: true },
        }),
      );
    renderStudio();
    fireEvent.click(await screen.findByRole("button", { name: "Explore entity" }));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    expect(screen.getByText("Dubai")).toBeInTheDocument();
    expect(screen.getByText("94%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(screen.getByText("الخصائص")).toBeInTheDocument();
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getAllByText("pilot-entity-001").some((node) => node.getAttribute("dir") === "ltr")).toBe(true);
  });

  it("returns to login when an entity request reports session expiry", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(jsonResponse({ error: "expired" }, 401));
    renderStudio();
    fireEvent.click(await screen.findByRole("button", { name: "Explore entity" }));
    expect(await screen.findByRole("link", { name: /continue to secure sign in/i })).toBeInTheDocument();
  });

  it("shows an actionable backend error", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(jsonResponse({ error: "unavailable" }, 503));
    renderStudio();
    fireEvent.click(await screen.findByRole("button", { name: "Explore entity" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("request could not be completed");
  });

  it("shows a session service error and supports retry", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ error: "unavailable" }, 503));
    renderStudio();
    expect(await screen.findByRole("heading", { name: "Studio is unavailable" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("switches between complete English LTR and Arabic RTL states", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ authenticated: true }));
    renderStudio();
    expect(await screen.findByText("Authenticated session")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(screen.getByText("جلسة موثّقة")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "استعراض الكيان" })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(screen.getByDisplayValue("pilot-entity-001")).toHaveAttribute("dir", "ltr");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
  });

  it("returns to sign in only after the BFF confirms logout", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ error: "unauthorized" }, 401));
    Object.defineProperty(document, "cookie", { configurable: true, value: "__Host-emg_studio_csrf=csrf-value" });
    renderStudio();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("link", { name: /continue to secure sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("Authenticated session")).not.toBeInTheDocument();
  });

  it("keeps the authenticated view and translates a logout failure", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ authenticated: true }))
      .mockResolvedValueOnce(jsonResponse({ error: "invalid csrf" }, 401));
    Object.defineProperty(document, "cookie", { configurable: true, value: "__Host-emg_studio_csrf=wrong" });
    renderStudio();
    await screen.findByText("Authenticated session");
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    fireEvent.click(screen.getByRole("button", { name: "تسجيل الخروج" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("فشل تسجيل الخروج");
    expect(screen.getByText("جلسة موثّقة")).toBeInTheDocument();
  });

  it("translates the unauthenticated state", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ error: "unauthorized" }, 401));
    renderStudio();
    await screen.findByRole("link", { name: /continue to secure sign in/i });
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(screen.getByRole("heading", { name: "الاتصال باستوديو EMG" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /المتابعة إلى تسجيل الدخول الآمن/ })).toBeInTheDocument();
  });
});
