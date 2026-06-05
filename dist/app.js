const state = {
  catalog: null,
  tableIndex: 0,
  query: "",
};

const els = {
  stats: document.querySelector("#stats"),
  tableSelect: document.querySelector("#tableSelect"),
  searchInput: document.querySelector("#searchInput"),
  tableTitle: document.querySelector("#tableTitle"),
  resultCount: document.querySelector("#resultCount"),
  tableHead: document.querySelector("#tableHead"),
  tableBody: document.querySelector("#tableBody"),
};

const catalog = await fetch("./assets/catalog.json").then((response) => {
  if (!response.ok) {
    throw new Error(`Could not load catalog: ${response.status}`);
  }
  return response.json();
});

state.catalog = catalog;
boot();

function boot() {
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
    render();
  });

  els.searchInput.addEventListener("input", () => {
    state.query = els.searchInput.value.trim().toLowerCase();
    render();
  });

  render();
}

function render() {
  const table = catalog.tables[state.tableIndex];
  const rows = filteredRows(table);

  els.tableTitle.textContent = table.targetClassLabel;
  els.resultCount.textContent = `${rows.length} of ${table.rows.length} rows`;

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

function filteredRows(table) {
  if (!state.query) {
    return table.rows;
  }
  return table.rows.filter((row) => row.searchText.includes(state.query));
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
