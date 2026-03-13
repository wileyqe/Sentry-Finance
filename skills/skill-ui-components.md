# Frontend UI Generation Rules
You are building a React/Vite frontend using Tailwind CSS. 
1. DO NOT write custom CSS or inline styles for complex UI elements.
2. You must rely exclusively on `shadcn/ui` for structural components (Tables, Buttons, Inputs, Select dropdowns, and Sheets/Drawers).
3. The primary interaction for editing a table row is opening a shadcn `Sheet` component on the right side of the screen.
4. For charts and data visualization (Pie charts, budget bars), you must use the `Tremor` React library.
5. All UI state updates modifying the database must use Optimistic UI patterns (update the visual state immediately, then await the backend SQL update).
