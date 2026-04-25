import { Button } from "@/components/ui/button";
import { useTheme } from "@/context/ThemeContext";

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <Button
      variant="outline"
      size="icon-lg"
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggleTheme}
      className="rounded-xl text-muted-foreground hover:text-primary hover:border-primary/30 hover:bg-primary/10 dark:hover:bg-primary/10"
    >
      <span className="material-symbols-outlined text-[18px]">
        {theme === "dark" ? "light_mode" : "dark_mode"}
      </span>
    </Button>
  );
}
