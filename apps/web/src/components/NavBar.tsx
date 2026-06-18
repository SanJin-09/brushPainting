import { Link, useLocation } from "react-router-dom";

export default function NavBar() {
  const location = useLocation();
  const path = location.pathname;

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <Link to="/">工笔重绘工作台</Link>
      </div>
      <div className="navbar-links">
        <Link to="/" className={path === "/" ? "active" : ""}>上传</Link>
      </div>
    </nav>
  );
}
