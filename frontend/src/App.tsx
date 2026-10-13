import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
    Activity,
    Bell,
    LayoutDashboard,
    Settings,
    Sun,
    Moon,
    ShieldCheck,
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
    const [polling, setPolling] = useState(15000);
    const [theme, setTheme] = useState(
        () => localStorage.getItem("fleet-theme") ?? "dark",
    );
    const [authOpen, setAuthOpen] = useState(false);
    const authDialog=useRef<HTMLDialogElement>(null);
    useEffect(()=>{if(authOpen)authDialog.current?.showModal();},[authOpen]);
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
                            <Activity size={25} />
                        </span>
                        <span>
                            Android Fleet<small>MONITOR & MANAGE</small>
                        </span>
                    </NavLink>
                    <p className="nav-label">WORKSPACE</p>
                    <nav aria-label="Main navigation">
                        <NavLink to="/" end>
                            <LayoutDashboard size={19} />
                            Fleet overview
                        </NavLink>
                        <NavLink to="/alerts">
                            <Bell size={19} />
                            Alerts
                        </NavLink>
                        <NavLink to="/management">
                            <Settings size={19} />
                            Device management
                        </NavLink>
                        {(auth.can("terminal:view") || auth.can("terminal:profile:manage")) && <NavLink to="/ssh"><ShieldCheck size={19} />SSH Connections</NavLink>}
                        <NavLink to="/operations"><Activity size={19} />Operations</NavLink>
                        {auth.can("audit.read") && <NavLink to="/audit"><ShieldCheck size={19} />Audit log</NavLink>}
                    </nav>
                    <div className="sidebar-footer">
                        <span className="status-dot online" />
                        ADB authenticated monitoring
                        <small>M4 · Local homelab workspace</small>
                    </div>
                </aside>
                <div className="workspace">
                    <header className="topbar">
                        <span className="muted">Android Fleet / Workspace</span>
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
                                    <Sun size={19} />
                                ) : (
                                    <Moon size={19} />
                                )}
                            </button>
                            <button
                                className={`button auth-button ${auth.token ? "authenticated" : ""}`}
                                onClick={() => setAuthOpen(true)}
                            >
                                <ShieldCheck size={17} />
                                {auth.identity ? `${auth.identity.identity} · ${auth.identity.role}` : "Sign in"}
                            </button>
                        </div>
                    </header>
                    <main id="main-content">
                        {!auth.identity && <p role="status">Sign in to access protected fleet data. {auth.error}</p>}
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
                <dialog ref={authDialog} className="auth-dialog" onCancel={()=>{setDraft("");setAuthOpen(false);}}>
                    <section
                        className="modal panel"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="auth-title"
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
                                    type="password"
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
                                <button className="primary" type="submit">
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
