import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider } from "@/i18n/i18n";
import { ApplicationShell } from "./application-shell";

const navigation = vi.hoisted(() => ({ pathname: "/dashboard", push: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname, useRouter: () => ({ push: navigation.push }) }));

function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<I18nProvider><QueryClientProvider client={client}><ApplicationShell><h1>Route content</h1></ApplicationShell></QueryClientProvider></I18nProvider>);
}

describe("enterprise application shell", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); navigation.pathname = "/dashboard"; navigation.push.mockReset(); });
  afterEach(() => vi.unstubAllGlobals());

  it("fails closed to secure sign in when unauthenticated", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ error: "unauthorized" }, 401));
    renderShell();
    expect(await screen.findByRole("link", { name: /continue to secure sign in/i })).toHaveAttribute("href", "/bff/auth/login");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("renders the authenticated English shell and current route", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ authenticated: true }));
    renderShell();
    expect(await screen.findByText("Authenticated session")).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Entities" })).toHaveAttribute("href", "/entities");
  });

  it("switches navigation to Arabic RTL and back to English LTR", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ authenticated: true }));
    renderShell();
    await screen.findByText("Authenticated session");
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(screen.getByRole("link", { name: "لوحة المعلومات" })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(document.documentElement).toHaveAttribute("dir", "ltr");
  });

  it("opens and closes the accessible mobile navigation drawer", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ authenticated: true }));
    renderShell();
    const open = await screen.findByRole("button", { name: "Open navigation" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getAllByRole("button", { name: "Close navigation" })[0]);
    expect(open).toHaveAttribute("aria-expanded", "false");
  });

  it("routes the global search entry without querying a backend", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ authenticated: true }));
    renderShell();
    fireEvent.submit(await screen.findByRole("search"));
    expect(navigation.push).toHaveBeenCalledWith("/search");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("returns to sign in only after confirmed server logout", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: true })).mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(response({ error: "unauthorized" }, 401));
    Object.defineProperty(document, "cookie", { configurable: true, value: "__Host-emg_studio_csrf=csrf-value" });
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("link", { name: /continue to secure sign in/i })).toBeInTheDocument();
  });

  it("keeps authenticated content visible when logout fails", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: true })).mockResolvedValueOnce(response({ error: "invalid csrf" }, 401));
    Object.defineProperty(document, "cookie", { configurable: true, value: "__Host-emg_studio_csrf=wrong" });
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("session remains active");
    expect(screen.getByText("Route content")).toBeInTheDocument();
  });
});
