import React, { useEffect, useState } from "react";

function apply(theme) {
  if (theme === "dark") document.documentElement.dataset.theme = "dark";
  else document.documentElement.removeAttribute("data-theme");
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "warm");
  useEffect(() => { apply(theme); }, [theme]);
  const flip = () => {
    const next = theme === "dark" ? "warm" : "dark";
    localStorage.setItem("theme", next);
    setTheme(next);
  };
  return (
    <button className="icon-btn" onClick={flip} aria-label="Toggle theme">
      {theme === "dark" ? "☀︎" : "☾"}
    </button>
  );
}
