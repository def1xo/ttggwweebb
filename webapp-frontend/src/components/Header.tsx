import React from 'react'
import { Link } from 'react-router-dom'


const Header: React.FC = () => {
return (
<header className="flex items-center justify-between p-4 border-b dark:border-gray-700">
<Link to="/" className="text-xl font-bold">TG Shop</Link>
<nav className="flex gap-4 items-center">
<Link to="/catalog">Каталог</Link>
<Link to="/cart">Корзина</Link>
</nav>
</header>
)
}
export default Header