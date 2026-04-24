// Map + RATP line color palette. Shared by user and admin pages.

const MAP_CENTER = [48.8566, 2.3522]; // Paris (Notre-Dame)
const MAP_ZOOM = 13;
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Official RATP line colors (https://www.ratp.fr).
const LINE_COLORS = {
  "1": "#FFCD00",
  "2": "#003CA6",
  "3": "#837902",
  "3bis": "#6EC4E8",
  "4": "#CF009E",
  "5": "#FF7E2E",
  "6": "#6ECA97",
  "7": "#FA9ABA",
  "7bis": "#6ECA97",
  "8": "#E19BDF",
  "9": "#B6BD00",
  "10": "#C9910D",
  "11": "#704B1C",
  "12": "#007852",
  "13": "#6EC4E8",
  "14": "#62259D",
};

const DEFAULT_LINE_COLOR = "#888";

function colorForLine(lineId) {
  return LINE_COLORS[lineId] || DEFAULT_LINE_COLOR;
}

const API_BASE = ""; // same origin
