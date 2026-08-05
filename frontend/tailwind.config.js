/**
 * Tokens visuais extraídos da REFERÊNCIA OBRIGATÓRIA (mocks das 18 telas — martech-plano.html).
 * Chrome vermelho Claro #D0271C / #A81E14; tema claro fixo (identidade do produto).
 * Paleta Journey Builder no canvas (jb-*) e paleta de gráficos validada CVD (ch1..ch4).
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        claro: {
          DEFAULT: "#D0271C", // chrome (topbar + rail)
          dark: "#A81E14", //    item ativo / pill do topo
          soft: "#FBEAE8",
          rose: "#F9CFC8", //    texto sobre vermelho
          rose2: "#F4B3AA", //   seções do rail / breadcrumb
          pale: "#FFE1DC", //    destaque do copiloto
          paper: "#FFF6F4",
          icon: "#E0604F", //    ícone inativo do rail
          avatar: "#E57365",
        },
        ink: "#182230",
        ink2: "#131C29",
        muted: "#68788C",
        faint: "#7C8CA0",
        slatex: "#5F7186",
        steel: "#33445A",
        ghost: "#8595A8",
        line: "#E1E7EE",
        line2: "#C9D3DD",
        linesoft: "#EDF1F5",
        page: "#F3F5F8",
        surface2: "#F7F9FB",
        flow: "#FBFCFD",
        blue: { DEFAULT: "#2B59C9", soft: "#E8EEFB" },
        good: { DEFAULT: "#177A4C", soft: "#E3F3EB" },
        warn: { DEFAULT: "#A36F0F", soft: "#FBF1DE", line: "#E5B96B", bg: "#FDF8EE" },
        crit: { DEFAULT: "#C0392B", soft: "#FAE7E4" },
        viol: { DEFAULT: "#6A48C9", soft: "#EFEAFB" },
        // paleta Journey Builder (canvas T7 — SDD §12)
        jb: {
          entry: "#2E844A", // entry source — verde
          msg: "#0B827C", //   mensagens — teal
          flow: "#DD7A01", //  flow control — laranja
          ein: "#9050E9", //   Einstein/otimização — roxo
          upd: "#0176D3", //   customer updates — azul
          exit: "#747E8B",
        },
        // gráficos previsto×realizado (Recharts)
        ch1: "#3A66D6",
        ch2: "#2FA394",
        ch3: "#D98E22",
        ch4: "#7A5AD9",
      },
      fontFamily: {
        sans: ['"Segoe UI"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"Cascadia Code"', "Consolas", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(22,32,43,.06), 0 8px 28px rgba(22,32,43,.08)",
        tile: "0 1px 2px rgba(22,32,43,.2)",
      },
    },
  },
  plugins: [],
};
