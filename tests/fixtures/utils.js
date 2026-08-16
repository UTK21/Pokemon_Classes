const { formatDate } = require("./date_utils");

function processData(items) {
  return items.map((item) => ({
    ...item,
    date: formatDate(item.timestamp),
  }));
}

const pipe = (...fns) => (x) => fns.reduce((v, f) => f(v), x);

module.exports = { processData, pipe };
