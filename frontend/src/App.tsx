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
    Menu,
    X,
    ChevronRight,
} from "lucide-react";
const OperationsPage = lazy(() => import("./features/control/OperationsPage"));
const AuditPage = lazy(() => import("./features/control/AuditPage"));
const FleetPage = lazy(() => import("./features/fleet/FleetPage"));
const DevicePage = lazy(() => import("./features/fleet/DevicePage"));
const AlertsPage = lazy(() => import("./features/alerts/AlertsPage"));
const SSHConnectionsPage = lazy(() => import("./features/terminal/SSHConnectionsPage"));
const ManagementPage = lazy(() => import("./features/management/ManagementPage"));
import { PollContext } from "./lib/hooks";
import { useAlertNotifications } from "./lib/alertNotifications";
import { useAuth } from "./lib/auth";
function AlertNotifications() {
    useAlertNotifications();
    return null;
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
        "/ssh": "SSH Connections", "/operations": "Operations", "/audit": "Audit log",
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
        if (!authOpen) return;
        authDialog.current?.showModal();
        return () => authTrigger.current?.focus();
    }, [authOpen]);
    useEffect(() => {
        document.title = `${pageTitle} · Android Fleet`;
    }, [pageTitle]);
    const [draft, setDraft] = useState("");
    const auth = useAuth();
    useEffect(() => {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem("fleet-theme", theme);
    }, [theme]);
    return (
        <PollContext.Provider value={polling}>
            <AlertNotifications />
            <a className="skip-link" href="#main-content">Skip to content</a>
            <div className="app-shell">
                <aside className="sidebar">
                    <NavLink to="/" className="brand">
                        <span className="brand-icon">
                            <Activity aria-hidden="true" size={25} />
                        </span>
                        <span>
                            Android Fleet<small>Monitor & manage</small>
                        </span>
                    </NavLink>
                    <button ref={navigationToggle} className="icon-button navigation-toggle" aria-label={navigationOpen ? "Close navigation" : "Open navigation"} aria-expanded={navigationOpen} aria-controls="main-navigation" onClick={() => setNavigationOpen(!navigationOpen)} onKeyDown={(event) => { if (event.key === "Escape") setNavigationOpen(false); }}>
                        {navigationOpen ? <X aria-hidden="true" size={20} /> : <Menu aria-hidden="true" size={20} />}
                    </button>
                    <p className="nav-label">Workspace</p>
                    <nav id="main-navigation" className={navigationOpen ? "navigation-open" : ""} aria-label="Main navigation" onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setNavigationOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") { setNavigationOpen(false); navigationToggle.current?.focus(); } }}>
                        <NavLink to="/" end>
                            <LayoutDashboard aria-hidden="true" size={19} />
                            Fleet overview
                        </NavLink>
                        <NavLink to="/alerts">
                            <Bell aria-hidden="true" size={19} />
                            Alerts
                        </NavLink>
                        <NavLink to="/management">
                            <Settings aria-hidden="true" size={19} />
                            Device management
                        </NavLink>
                        {(auth.can("terminal:view") || auth.can("terminal:profile:manage")) && <NavLink to="/ssh"><ShieldCheck aria-hidden="true" size={19} />SSH Connections</NavLink>}
                        <NavLink to="/operations"><Activity aria-hidden="true" size={19} />Operations</NavLink>
                        {auth.can("audit.read") && <NavLink to="/audit"><ShieldCheck aria-hidden="true" size={19} />Audit log</NavLink>}
                    </nav>
                    <div className="sidebar-footer">
                        <ShieldCheck aria-hidden="true" size={15} />
                        Authenticated ADB
                        <small>Android fleet workspace</small>
                    </div>
                </aside>
                <div className="workspace">
                    <header className="topbar">
                        <span className="breadcrumb"><span className="muted">Workspace</span><ChevronRight size={14} aria-hidden="true" /><span>{pageTitle}</span></span>
                        <div className="topbar-actions">
                            <label className="poll-label">
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
                            token stays in memory and is cleared when this page
                            closes or reloads.
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
        </PollContext.Provider>
    );
}
