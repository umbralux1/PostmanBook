/** Сборка CSS: npx tailwindcss@3 -i app/static/css/tailwind.src.css -o app/static/css/tailwind.css --minify */
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/builder.js"],
  theme: { extend: {} },
  plugins: [],
};
