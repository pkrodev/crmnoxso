/** Konfiguracja Tailwinda dla NOXSO CRM.
 *
 * Używana przez standalone CLI (jeden plik wykonywalny, bez Node'a i npm).
 * Wersja 3.x — v4 porzuciła plik konfiguracyjny na rzecz dyrektyw w CSS.
 *
 * Paleta pochodzi wprost z logo: bursztyn #FFAF00 (31,6% pikseli) i czerń
 * (28,3%). To marka dwukolorowa — kolory spoza tej palety są zarezerwowane
 * wyłącznie dla stanów semantycznych.
 */
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        amber: {
          50: "#FAF2E1",
          100: "#F5E4BF",
          200: "#F0D395",
          300: "#EDC46B",
          400: "#F2B93D",
          500: "#FFAF00",
          600: "#DB9600",
          700: "#B27A00",
          800: "#8C6000",
          900: "#6B4A00",
          950: "#473100",
        },
        ink: {
          50: "#FAFAFA",
          200: "#E5E5E5",
          500: "#737373",
          700: "#404040",
          900: "#171717",
          950: "#0A0A0A",
        },
        // Stany semantyczne. Ostrzeżenie jest POMARAŃCZOWE, nie żółte —
        // żółć zlałaby się z bursztynem marki.
        success: "#15803D",
        warning: "#EA580C",
        danger: "#B91C1C",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      fontSize: {
        // Gęsty, narzędziowy interfejs — domyślny rozmiar tabel jest mniejszy
        // niż w typowym Tailwindzie, żeby zmieścić więcej wierszy bez scrolla.
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.125rem" }],
        base: ["0.875rem", { lineHeight: "1.25rem" }],
      },
      letterSpacing: {
        section: "0.12em",
      },
    },
  },
  plugins: [],
};
