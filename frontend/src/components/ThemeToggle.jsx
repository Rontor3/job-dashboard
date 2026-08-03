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
    <button onClick={flip} aria-label="Toggle theme"
      style={{ background: "transparent", border: "0.5px solid var(--hairline)",
               borderRadius: "var(--radius-pill)", padding: "6px 10px", cursor: "pointer",
               color: "var(--ink-soft)", fontSize: 13 }}>
      {theme === "dark" ? "☀︎" : "☾"}
    </button>
  );
}
