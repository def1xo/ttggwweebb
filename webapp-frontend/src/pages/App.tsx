// webapp-frontend/src/App.tsx
import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import Catalog from "./pages/Catalog";
import ProductPage from "./pages/ProductPage";
import Checkout from "./pages/Checkout";
import ManagerWithdrawForm from "./pages/ManagerWithdrawForm";
import ManagerWithdrawList from "./pages/ManagerWithdrawList";
import AdminWithdrawsList from "./pages/AdminWithdrawsList";
import AdminOrdersList from "./pages/AdminOrdersList";

function App() {
  return (
    <BrowserRouter>
      {/* Header component if exists */}
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/product/:slug" element={<ProductPage />} />
        <Route path="/checkout" element={<Checkout />} />
        {/* Manager routes */}
        <Route path="/manager/withdraw" element={<ManagerWithdrawForm />} />
        <Route path="/manager/withdraws" element={<ManagerWithdrawList />} />
        {/* Admin routes */}
        <Route path="/admin/withdraws" element={<AdminWithdrawsList />} />
        <Route path="/admin/orders" element={<AdminOrdersList />} />
        {/* Add more routes as needed */}
      </Routes>
    </BrowserRouter>
  );
}

export default App;
