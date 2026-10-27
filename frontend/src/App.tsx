import { lazy, Suspense, useEffect, useRef, useState, type MouseEvent } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
    Activity,
    Bell,
    LayoutDashboard,
    Settings,
    Sun,
    Moon,
    ShieldCheck,
    ScrollText,
    FlaskConical,
    SlidersHorizontal,
    TerminalSquare,
    Menu,
    X,
    ChevronRight,
    Search,
} from "lucide-react";
const OperationsPage = lazy(() => import("./features/control/OperationsPage"));
const AuditPage = lazy(() => import("./features/control/AuditPage"));
const FleetPage = lazy(() => import("./features/fleet/FleetPage"));
const DevicePage = lazy(() => import("./features/fleet/DevicePage"));
const AlertsPage = lazy(() => import("./features/alerts/AlertsPage"));
const SSHConnectionsPage = lazy(() => import("./features/terminal/SSHConnectionsPage"));
const ManagementPage = lazy(() => import("./features/management/ManagementPage"));
const RunsPage = lazy(() => import("./features/runs/RunsPage"));
const SettingsPage = lazy(() => import("./features/settings/SettingsPage"));
import { PollContext, useDevices } from "./lib/hooks";
import { fleetGroup } from "./features/fleet/fleetState";
import { useAlertNotifications } from "./lib/alertNotifications";
import CommandPalette from "./components/CommandPalette";
import { OPEN_ACCESS_EVENT } from "./lib/api";
import { useAuth } from "./lib/auth";
function BrandMark() {
    return (
        <span className="brand-icon" aria-hidden="true">
            <svg viewBox="0 0 28 28" width="28" height="28">
                <rect x="2.5" y="5.5" width="9" height="17" rx="2.2" />
                <rect x="16.5" y="5.5" width="9" height="17" rx="2.2" />
                <circle cx="7" cy="19" r="1.3" className="brand-led" />
                <circle cx="21" cy="19" r="1.3" className="brand-led" />
            </svg>
        </span>
    );
}
function FleetPulse() {
    const devices = useDevices();
    if (!devices.data?.length) return null;
    const online = devices.data.filter((device) => fleetGroup(device) === "online").length;
    const attention = devices.data.filter((device) => fleetGroup(device) === "degraded").length;
    return (
        <div className="sidebar-footer">
            <div className="fleet-pulse" role="img" aria-label={`${online} of ${devices.data.length} devices online`}>
                {devices.data.map((device) => (
                    <i key={device.id} className={`led ${fleetGroup(device)}`} />
                ))}
            </div>
            <span><strong>{online}</strong> of {devices.data.length} online{attention ? ` · ${attention} need attention` : ""}</span>
        </div>
    );
}
export default function App() {
    const location = useLocation();
    const [navigationOpen, setNavigationOpen] = useState(false);
    const navigationToggle = useRef<HTMLButtonElement>(null);
    const previousPath = useRef(location.pathname);
    const mainContent = useRef<HTMLElement>(null);
    useEffect(() => {
        if (previousPath.current === location.pathname) return;
        previousPath.current = location.pathname;
        mainContent.current?.focus({ preventScroll: true });
        window.scrollTo(0, 0);
    }, [location.pathname]);
    const pageTitle = location.pathname.startsWith("/devices/") ? "Device details" : ({
        "/": "Fleet overview", "/alerts": "Alerts", "/management": "Device management",
        "/ssh": "SSH Connections", "/operations": "Operations", "/audit": "Audit log", "/runs": "Program runs", "/settings": "Settings",
    }[location.pathname] ?? "Page not found");
    const [polling, setPolling] = useState(15000);
    const [theme, setTheme] = useState(
        () => localStorage.getItem("fleet-theme") ?? "dark",
    );
    const [authOpen, setAuthOpen] = useState(false);
    const authDialog = useRef<HTMLDialogElement>(null);
    const authTrigger = useRef<HTMLButtonElement>(null);
    function openAccess(event: MouseEvent<HTMLButtonElement>) {
        authTrigger.current = event.currentTarget;
        setAuthOpen(true);
    }
    useEffect(() => {
        const open = () => {
            if (document.activeElement instanceof HTMLButtonElement)
                authTrigger.current = document.activeElement;
            setAuthOpen(true);
        };
        window.addEventListener(OPEN_ACCESS_EVENT, open);
        return () => window.removeEventListener(OPEN_ACCESS_EVENT, open);
    }, []);
    useEffect(() => {
        if (!authOpen) return;
        authDialog.current?.showModal();
        return () => authTrigger.current?.focus();
    }, [authOpen]);
    useEffect(() => {
        document.title = `${pageTitle} · Android Fleet`;
    }, [pageTitle]);
    const [draft, setDraft] = useState("");
    const auth = useAuth();
    const firing = useAlertNotifications(polling);
    const [paletteOpen, setPaletteOpen] = useState(false);
    useEffect(() => {
        const open = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                setPaletteOpen(true);
            }
        };
        window.addEventListener("keydown", open);
        return () => window.removeEventListener("keydown", open);
    }, []);
    const paletteRoutes = [
        { label: "Fleet overview", path: "/" },
        { label: "Alerts", path: "/alerts" },
        { label: "Operations", path: "/operations" },
        ...(auth.can("terminal:view") ? [{ label: "Program runs", path: "/runs" }] : []),
        ...(auth.can("device.read") ? [{ label: "Settings", path: "/settings" }] : []),
        ...(auth.can("terminal:view") || auth.can("terminal:profile:manage") ? [{ label: "SSH Connections", path: "/ssh" }] : []),
        { label: "Device management", path: "/management" },
        ...(auth.can("audit.read") ? [{ label: "Audit log", path: "/audit" }] : []),
    ];
    useEffect(() => {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem("fleet-theme", theme);
    }, [theme]);
    return (
        <PollContext.Provider value={polling}>
            <a className="skip-link" href="#main-content">Skip to content</a>
            <div className="app-shell">
                <aside className="sidebar">
                    <NavLink to="/" className="brand">
                        <BrandMark />
                        <span>
                            Android Fleet<small>Lab bench</small>
                        </span>
                    </NavLink>
                    <button ref={navigationToggle} className="icon-button navigation-toggle" aria-label={navigationOpen ? "Close navigation" : "Open navigation"} aria-expanded={navigationOpen} aria-controls="main-navigation" onClick={() => setNavigationOpen(!navigationOpen)} onKeyDown={(event) => { if (event.key === "Escape") setNavigationOpen(false); }}>
                        {navigationOpen ? <X aria-hidden="true" size={20} /> : <Menu aria-hidden="true" size={20} />}
                    </button>
                    <nav id="main-navigation" className={navigationOpen ? "navigation-open" : ""} aria-label="Main navigation" onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setNavigationOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") { setNavigationOpen(false); navigationToggle.current?.focus(); } }}>
                        <p className="nav-label">Monitor</p>
                        <NavLink to="/" end>
                            <LayoutDashboard aria-hidden="true" size={18} />
                            Fleet overview
                        </NavLink>
                        <NavLink to="/alerts">
                            <Bell aria-hidden="true" size={18} />
                            Alerts
                            {firing ? <span className="nav-count" aria-hidden="true">{firing}</span> : null}
                        </NavLink>
                        <p className="nav-label">Control</p>
                        <NavLink to="/operations"><Activity aria-hidden="true" size={18} />Operations</NavLink>
                        {auth.can("terminal:view") && <NavLink to="/runs"><FlaskConical aria-hidden="true" size={18} />Program runs</NavLink>}
                        {(auth.can("terminal:view") || auth.can("terminal:profile:manage")) && <NavLink to="/ssh"><TerminalSquare aria-hidden="true" size={18} />SSH Connections</NavLink>}
                        <p className="nav-label">Administer</p>
                        <NavLink to="/management">
                            <Settings aria-hidden="true" size={18} />
                            Device management
                        </NavLink>
                        {auth.can("audit.read") && <NavLink to="/audit"><ScrollText aria-hidden="true" size={18} />Audit log</NavLink>}
                        {auth.can("device.read") && <NavLink to="/settings"><SlidersHorizontal aria-hidden="true" size={18} />Settings</NavLink>}
                    </nav>
                    <FleetPulse />
                </aside>
                <div className="workspace">
                    <header className="topbar">
                        <span className="breadcrumb"><span className="muted">Workspace</span><ChevronRight size={14} aria-hidden="true" /><span>{pageTitle}</span></span>
                        <div className="topbar-actions">
                            <button type="button" className="palette-trigger" aria-label="Jump to device or page" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K">
                                <Search aria-hidden="true" size={16} />
                                <span className="palette-text">Jump to…</span>
                                <kbd>Ctrl K</kbd>
                            </button>
                            <label className="poll-label">
                                <span className={`live-led ${polling ? "on" : ""}`} aria-hidden="true" />
                                Refresh
                                <select
                                    aria-label="Automatic refresh interval"
                                    value={polling}
                                    onChange={(e) =>
                                        setPolling(Number(e.target.value))
                                    }
                                >
                                    <option value={5000}>5 sec</option>
                                    <option value={15000}>15 sec</option>
                                    <option value={30000}>30 sec</option>
                                    <option value={60000}>1 min</option>
                                    <option value={0}>Paused</option>
                                </select>
                            </label>
                            <button
                                className="icon-button"
                                aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
                                onClick={() =>
                                    setTheme(
                                        theme === "dark" ? "light" : "dark",
                                    )
                                }
                            >
                                {theme === "dark" ? (
                                    <Sun aria-hidden="true" size={19} />
                                ) : (
                                    <Moon aria-hidden="true" size={19} />
                                )}
                            </button>
                            <button
                                className={`button auth-button ${auth.token ? "authenticated" : ""}`}
                                onClick={openAccess}
                            >
                                <ShieldCheck aria-hidden="true" size={17} />
                                {auth.identity ? `${auth.identity.identity} · ${auth.identity.role}` : "Sign in"}
                            </button>
                        </div>
                    </header>
                    <main ref={mainContent} id="main-content" tabIndex={-1}>
                        {!auth.identity && <div className="access-notice"><ShieldCheck aria-hidden="true" size={20} /><div><strong>Connect to your fleet</strong><p>Sign in to view protected device data and permitted actions.</p></div><button onClick={openAccess}>Sign in</button></div>}
                        <Suspense fallback={<div className="panel skeleton" role="status" aria-label="Loading page" />}><Routes>
                            <Route path="/" element={<FleetPage />} />
                            <Route
                                path="/devices/:id"
                                element={<DevicePage />}
                            />
                            <Route path="/ssh" element={<SSHConnectionsPage />} />
                            <Route path="/alerts" element={<AlertsPage />} />
                            <Route path="/operations" element={<OperationsPage />} />
                            <Route path="/runs" element={<RunsPage />} />
                            <Route path="/settings" element={<SettingsPage />} />
                            <Route path="/audit" element={<AuditPage />} />
                            <Route
                                path="/management"
                                element={<ManagementPage />}
                            />
                            <Route
                                path="*"
                                element={
                                    <div className="panel empty">
                                        <h1>Page not found</h1>
                                        <NavLink to="/">
                                            Return to fleet
                                        </NavLink>
                                    </div>
                                }
                            />
                        </Routes></Suspense>
                    </main>
                </div>
            </div>
            {authOpen && (
                <dialog ref={authDialog} className="auth-dialog" aria-labelledby="auth-title" onCancel={()=>{setDraft("");setAuthOpen(false);}}>
                    <section
                        className="modal panel"
                    >
                        <h2 id="auth-title">Fleet access</h2>
                        <p className="muted">
                            Enter your viewer, operator or administrator token to access
                            fleet data and permitted actions. The
                            token is remembered in this browser until you sign out
                            or it stops being valid.
                        </p>
                        {auth.error && <p className="error" role="alert">{auth.error}</p>}
                        <form
                            onSubmit={(e) => {
                                e.preventDefault();
                                auth.setToken(draft);
                                setDraft("");
                                setAuthOpen(false);
                            }}
                        >
                            <label>
                                Control token
                                <input
                                    name="control-token"
                                    type="password"
                                    spellCheck={false}
                                    autoComplete="off"
                                    value={draft}
                                    onChange={(e) => setDraft(e.target.value)}
                                    autoFocus
                                />
                            </label>
                            <div className="actions">
                                <button
                                    type="button"
                                    onClick={() => {
                                        auth.setToken("");
                                        setDraft("");
                                        setAuthOpen(false);
                                    }}
                                >
                                    Clear access
                                </button>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setDraft("");
                                        setAuthOpen(false);
                                    }}
                                >
                                    Cancel
                                </button>
                                <button className="primary" type="submit" disabled={!draft.trim()}>
                                    Authorize
                                </button>
                            </div>
                        </form>
                    </section>
                </dialog>
            )}
            <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} routes={paletteRoutes} />
        </PollContext.Provider>
    );
}
