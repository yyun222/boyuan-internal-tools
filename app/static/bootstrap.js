// Start feature modules only after every responsibility-specific script has loaded.
currentUserRequest.then((data) => {
  if (!data?.user) return;
  currentUser = data.user;
  sessionStorage.setItem("boyuan_current_user", JSON.stringify(data.user));
  $("#current-user").textContent = data.user.email || data.user.username || "";
  applyPermissions(data.user);
  loadHomeFunFacts();
  loadNextHoliday();
  if (data.user.permissions?.manageUsers) {
    loadRoles();
    loadUsers();
    loadActivityLogs();
  }
  if (data.user.permissions?.viewAssetLedger) initAssetLedger(data.user);
  if (data.user.permissions?.viewStockOrders) initStockOrders(data.user);
});
