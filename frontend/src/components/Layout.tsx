import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">Journey Investigation &amp; Recovery</div>
        <nav>
          <NavLink to="/cases" className={({ isActive }) => (isActive ? "active" : "")}>
            Cases
          </NavLink>
          <NavLink to="/approvals" className={({ isActive }) => (isActive ? "active" : "")}>
            Approvals
          </NavLink>
          {user?.role === "admin" && (
            <>
              <span className="small muted" style={{ margin: "0 4px" }}>
                |
              </span>
              <NavLink to="/debug/events" className={({ isActive }) => (isActive ? "active" : "")}>
                Live feed
              </NavLink>
              <NavLink to="/debug/timeline" className={({ isActive }) => (isActive ? "active" : "")}>
                Timeline explorer
              </NavLink>
              <NavLink to="/debug/conflicts" className={({ isActive }) => (isActive ? "active" : "")}>
                Conflicts
              </NavLink>
              <NavLink to="/debug/health" className={({ isActive }) => (isActive ? "active" : "")}>
                Pipeline health
              </NavLink>
            </>
          )}
        </nav>
        <div className="user">
          {user && (
            <>
              <span className="badge role">{user.role}</span>
              <span>{user.display_name}</span>
              <button onClick={logout}>Log out</button>
            </>
          )}
        </div>
      </header>
      <main style={{ flex: 1 }}>
        <Outlet />
      </main>
    </div>
  );
}
