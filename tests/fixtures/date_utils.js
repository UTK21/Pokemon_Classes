function formatDate(timestamp) {
  return new Date(timestamp).toISOString().split("T")[0];
}

function parseDate(str) {
  return new Date(str).getTime();
}

module.exports = { formatDate, parseDate };
