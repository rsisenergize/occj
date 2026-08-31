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
