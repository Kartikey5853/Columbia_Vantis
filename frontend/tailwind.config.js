/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        vantis: {
          blue: "#079FE0",
          cyan: "#00d2ff",
          dark: "#0b192c",
          bgLight: "#F8FAFC",
          panelLight: "#EAF6FE",
          border: "#E2E8F0",
        }
      }
    },
  },
  plugins: [],
}
