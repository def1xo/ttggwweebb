import React, { useEffect, useState } from 'react'
import api from '../services/api'
import { useParams } from 'react-router-dom'

const AdminProductEdit: React.FC = () => {
  const { id } = useParams()
  const [product, setProduct] = useState<any>(null)
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [visible, setVisible] = useState(true)
  const [categoryId, setCategoryId] = useState<number | null>(null)

  useEffect(() => {
    if (!id) return
    api.get(`/products/${id}`).then(r => { setProduct(r.data); setName(r.data.name); setPrice(r.data.base_price); setVisible(true); })
  }, [id])

  const save = async () => {
    const payload = { name, base_price: price, visible, category_id: categoryId }
    await api.put(`/admin/products/${id}`, payload)
    alert('Saved')
  }

  if (!product) return <div>Loading...</div>
  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <h1>Edit product #{id}</h1>
      <input value={name} onChange={e => setName(e.target.value)} />
      <input value={price} onChange={e => setPrice(e.target.value)} />
      <label><input type="checkbox" checked={visible} onChange={e => setVisible(e.target.checked)} /> Visible</label>
      <button onClick={save}>Save</button>
    </div>
  )
}
export default AdminProductEdit