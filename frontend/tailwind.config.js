/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#F7F8FC", panel: "#FFFFFF", raised: "#F1F4FB", line: "#E1E7F0" },
        brand: { DEFAULT: "#635BFF", soft: "#ECEAFF" },
        good: "#14835B", warn: "#AF6B0B", risk: "#CB4056",
        text: { DEFAULT: "#17233F", muted: "#62718A", faint: "#8894A8" },
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
    },
  },
  plugins: [],
};
