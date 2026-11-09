// Мост для pytest: читает {expected, history, state} из stdin,
// прогоняет checker.js и печатает результат в stdout.
const path = require("node:path");
const C = require(path.join(__dirname, "../../app/static/js/checker.js"));

let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const { expected, history, state } = JSON.parse(input);
  process.stdout.write(JSON.stringify(C.evaluateTask(expected, history, state || {})));
});
