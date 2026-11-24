// Start feature modules only after every responsibility-specific script has loaded.
currentUserRequest.then((data) => {
  if (!data?.user) return;
  currentUser = data.user;
  sessionStorage.setItem("boyuan_current_user", JSON.stringify(data.user));
  $("#current-user").textContent = data.user.email || data.user.username || "";
  if (data.user.mustSetPassword) {
    window.showCafeteriaPasswordSetup();
    return;
  }
  applyPermissions(data.user);
  window.refreshCafeteriaNav();
  loadHomeFunFacts();
  loadNextHoliday();
  if (data.user.permissions?.manageUsers) {
    loadRoles();
    loadUsers();
    loadActivityLogs();
  }
  if (data.user.permissions?.viewAssetLedger) initAssetLedger(data.user);
  if (data.user.permissions?.viewStockOrders) initStockOrders(data.user);
  const initialView = new URLSearchParams(window.location.search).get("view");
  const params = new URLSearchParams(window.location.search);
  const stockOrderId = Number(params.get("stockOrder"));
  if (stockOrderId > 0 && data.user.permissions?.viewStockOrders) {
    $("#stock-orders-nav")?.click();
    const mode = params.get("stockOrderMode") === "edit" ? "edit" : "view";
    window.openStockOrder?.(stockOrderId, mode);
  }
  if (initialView === "stock-orders" && data.user.permissions?.viewStockOrders) {
    $("#stock-orders-nav")?.click();
  }
});
