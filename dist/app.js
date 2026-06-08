import Fuse from "./vendor/fuse.min.mjs";

const SEARCH_KEYS = [
  { name: "label", weight: 0.45 },
  { name: "curie", weight: 0.25 },
  { name: "searchText", weight: 0.3 },
];

const FUSE_OPTIONS = {
  includeScore: true,
  ignoreLocation: true,
  threshold: 0.35,
  useExtendedSearch: true,
  keys: SEARCH_KEYS,
};

const state = {
  catalog: null,
  searchIndexes: [],
  tableIndex: 0,
  query: "",
  viewMode: "table",
  collapsedHierarchyIds: new Set(),
};

const els = {
  stats: document.querySelector("#stats"),
  siteTitle: document.querySelector("h1"),
  tableSelect: document.querySelector("#tableSelect"),
  modeControl: document.querySelector(".mode-control"),
  modeButtons: document.querySelectorAll("[data-view-mode]"),
  searchInput: document.querySelector("#searchInput"),
  tableTitle: document.querySelector("#tableTitle"),
  resultCount: document.querySelector("#resultCount"),
  tableHead: document.querySelector("#tableHead"),
  tableBody: document.querySelector("#tableBody"),
  tableWrap: document.querySelector(".table-wrap"),
  hierarchyWrap: document.querySelector("#hierarchyWrap"),
};

const catalog = await fetch("./assets/catalog.json").then((response) => {
  if (!response.ok) {
    throw new Error(`Could not load catalog: ${response.status}`);
  }
  return response.json();
});

const siteConfig = await fetch("./assets/site-config.json")
  .then((response) => (response.ok ? response.json() : {}))
  .catch(() => ({}));

state.catalog = catalog;
state.searchIndexes = catalog.tables.map((table) => new Fuse(table.rows, FUSE_OPTIONS));
boot();

function boot() {
  const title = siteConfig.title || "Vocabulary Browser";
  document.title = title;
  els.siteTitle.textContent = title;
  els.stats.textContent = `${catalog.meta.sourceFiles} files | ${catalog.meta.triples} triples`;

  els.tableSelect.replaceChildren(
    ...catalog.tables.map((table, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${table.targetClassLabel} (${table.rows.length})`;
      return option;
    })
  );

  els.tableSelect.addEventListener("change", () => {
    state.tableIndex = Number(els.tableSelect.value);
    state.collapsedHierarchyIds.clear();
    render();
  });

  els.searchInput.addEventListener("input", () => {
    state.query = els.searchInput.value.trim();
    state.collapsedHierarchyIds.clear();
    render();
  });

  els.modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.viewMode = button.dataset.viewMode;
      render();
    });
  });

  render();
}

function render() {
  const table = catalog.tables[state.tableIndex];
  const rows = filteredRows(table);
  if (state.viewMode === "hierarchy" && !tableSupportsHierarchy(table)) {
    state.viewMode = "table";
  }

  els.tableTitle.textContent = table.targetClassLabel;
  els.resultCount.textContent = `${rows.length} of ${table.rows.length} rows`;

  updateModeButtons(table);
  els.tableWrap.hidden = state.viewMode !== "table";
  els.hierarchyWrap.hidden = state.viewMode !== "hierarchy";

  if (state.viewMode === "hierarchy") {
    renderHierarchy(table, rows);
    return;
  }

  renderTable(table, rows);
}

function renderTable(table, rows) {
  els.tableHead.replaceChildren(headerRow(table));
  els.tableBody.replaceChildren(...rows.slice(0, 250).map((row) => bodyRow(table, row)));

  if (rows.length > 250) {
    const overflowRow = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = table.fields.length + 1;
    cell.className = "overflow";
    cell.textContent = `Showing first 250 matches. Refine the search to narrow ${rows.length} results.`;
    overflowRow.append(cell);
    els.tableBody.append(overflowRow);
  }
}

function renderHierarchy(table, rows) {
  const hierarchy = table.hierarchy;
  if (!hierarchy || !hierarchy.nodes) {
    els.hierarchyWrap.replaceChildren(emptyState("No hierarchy data is available for this table."));
    return;
  }

  const matchedIds = new Set(rows.map((row) => row.id));
  const rowsById = new Map(table.rows.map((row) => [row.id, row]));
  const visibleIds = visibleHierarchyIds(hierarchy, matchedIds);
  const roots = hierarchy.roots.filter((id) => visibleIds.has(id));
  const list = document.createElement("ol");
  list.className = "hierarchy-tree";

  roots.forEach((id) => {
    const item = hierarchyItem(table, hierarchy, id, visibleIds, matchedIds, rowsById, new Set());
    if (item) {
      list.append(item);
    }
  });

  els.hierarchyWrap.replaceChildren(list.childElementCount ? list : emptyState("No matching concepts."));
}

function visibleHierarchyIds(hierarchy, matchedIds) {
  if (!state.query) {
    return new Set(Object.keys(hierarchy.nodes));
  }

  const visibleIds = new Set();
  matchedIds.forEach((id) => {
    let current = id;
    const seen = new Set();
    while (current && hierarchy.nodes[current] && !seen.has(current)) {
      visibleIds.add(current);
      seen.add(current);
      current = hierarchy.nodes[current].parents[0];
    }
  });
  return visibleIds;
}

function hierarchyItem(table, hierarchy, id, visibleIds, matchedIds, rowsById, pathIds) {
  if (pathIds.has(id)) {
    return null;
  }

  const node = hierarchy.nodes[id];
  if (!node || !visibleIds.has(id)) {
    return null;
  }

  const item = document.createElement("li");
  item.className = "hierarchy-node";
  if (matchedIds.has(id)) {
    item.classList.add("is-match");
  }

  const row = document.createElement("div");
  row.className = "hierarchy-row";
  row.style.setProperty("--depth", String(node.depth ?? 0));
  row.title = hierarchyTooltip(table, rowsById.get(id));
  row.setAttribute("aria-label", row.title);

  const label = document.createElement("span");
  label.className = "hierarchy-label";
  label.textContent = node.label || node.curie;

  const childIds = node.children.filter((childId) => visibleIds.has(childId));
  const isCollapsed = state.collapsedHierarchyIds.has(id);
  const toggle = hierarchyToggle(node, childIds, isCollapsed);

  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "copy-button";
  copyButton.textContent = "Copy IRI";
  copyButton.addEventListener("click", () => copyToClipboard(node.id, copyButton));

  row.append(toggle, label, copyButton);
  item.append(row);

  if (childIds.length > 0 && !isCollapsed) {
    const childList = document.createElement("ol");
    childList.className = "hierarchy-children";
    childIds.forEach((childId) => {
      const child = hierarchyItem(
        table,
        hierarchy,
        childId,
        visibleIds,
        matchedIds,
        rowsById,
        new Set([...pathIds, id])
      );
      if (child) {
        childList.append(child);
      }
    });
    item.append(childList);
  }

  return item;
}

function hierarchyToggle(node, childIds, isCollapsed) {
  if (childIds.length === 0) {
    const spacer = document.createElement("span");
    spacer.className = "hierarchy-toggle-spacer";
    return spacer;
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "hierarchy-toggle";
  button.textContent = isCollapsed ? "+" : "-";
  button.title = isCollapsed ? "Expand branch" : "Collapse branch";
  button.setAttribute("aria-label", `${isCollapsed ? "Expand" : "Collapse"} ${node.label || node.curie}`);
  button.setAttribute("aria-expanded", String(!isCollapsed));
  button.addEventListener("click", () => {
    if (isCollapsed) {
      state.collapsedHierarchyIds.delete(node.id);
    } else {
      state.collapsedHierarchyIds.add(node.id);
    }
    render();
  });
  return button;
}

function hierarchyTooltip(table, rowData) {
  if (!rowData) {
    return "No row details available.";
  }

  const lines = table.fields
    .map((field) => {
      const values = rowData.values[field.key] ?? [];
      return values.length > 0 ? `${field.label}: ${values.join("; ")}` : "";
    })
    .filter(Boolean);

  return lines.length > 0 ? lines.join("\n") : "No row details available.";
}

async function copyToClipboard(text, button) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopy(text);
    }
    flashCopyState(button, "Copied");
  } catch {
    flashCopyState(button, "Copy failed");
  }
}

function fallbackCopy(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.className = "clipboard-fallback";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function flashCopyState(button, text) {
  const originalText = button.textContent;
  button.textContent = text;
  window.setTimeout(() => {
    button.textContent = originalText;
  }, 1200);
}

function emptyState(message) {
  const element = document.createElement("p");
  element.className = "empty-state";
  element.textContent = message;
  return element;
}

function tableSupportsHierarchy(table) {
  return Boolean(table.hierarchyEnabled && table.hierarchy && table.hierarchy.nodes);
}

function updateModeButtons(table) {
  const supportsHierarchy = tableSupportsHierarchy(table);
  els.modeControl.hidden = !supportsHierarchy;
  els.modeButtons.forEach((button) => {
    if (button.dataset.viewMode === "hierarchy") {
      button.disabled = !supportsHierarchy;
    }
    const isActive = button.dataset.viewMode === state.viewMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function filteredRows(table) {
  if (!state.query) {
    return table.rows;
  }
  return state.searchIndexes[state.tableIndex]
    .search(searchQuery(state.query))
    .map((result) => result.item);
}

function searchQuery(query) {
  const tokens = query.split(/\s+/).filter(Boolean);

  if (tokens.length === 1) {
    return tokens[0];
  }

  return {
    $and: tokens.map((token) => ({
      $or: SEARCH_KEYS.map((key) => ({ [key.name]: token })),
    })),
  };
}

function headerRow(table) {
  const row = document.createElement("tr");
  row.append(th("IRI"));
  table.fields.forEach((field) => row.append(th(field.label)));
  return row;
}

function bodyRow(table, rowData) {
  const row = document.createElement("tr");
  const iriCell = document.createElement("td");
  const link = document.createElement("a");
  link.href = rowData.id;
  link.textContent = rowData.curie;
  link.target = "_blank";
  link.rel = "noreferrer";
  iriCell.append(link);
  row.append(iriCell);

  table.fields.forEach((field) => {
    const cell = document.createElement("td");
    const values = rowData.values[field.key] ?? [];
    cell.append(...renderValues(values));
    row.append(cell);
  });

  return row;
}

function renderValues(values) {
  if (values.length === 0) {
    return [document.createTextNode("")];
  }

  return values.flatMap((value, index) => {
    const nodes = [];
    if (index > 0) {
      nodes.push(document.createTextNode("; "));
    }

    if (isHttpIri(value)) {
      const link = document.createElement("a");
      link.href = value;
      link.textContent = value;
      link.target = "_blank";
      link.rel = "noreferrer";
      nodes.push(link);
    } else {
      nodes.push(document.createTextNode(value));
    }

    return nodes;
  });
}

function isHttpIri(value) {
  return typeof value === "string" && /^https?:\/\//.test(value);
}

function th(text) {
  const cell = document.createElement("th");
  cell.scope = "col";
  cell.textContent = text;
  return cell;
}
