const basis = document.getElementById("date_basis");
const statusFilter = document.getElementById("status");
if (basis && statusFilter) {
  basis.addEventListener("change", () => {
    statusFilter.disabled = basis.value === "completed";
    if (statusFilter.disabled) statusFilter.value = "COMPLETED";
    else if (statusFilter.value === "COMPLETED") statusFilter.value = "";
  });
}
