import React, { useState } from 'react'
import api from '../services/api'

const AdminCategoryCreate: React.FC = () => {
  const [name, setName] = useState('')
  const create = async () => {
    if (!name) return
    const res = await api.post('/admin/categories', { name })
    alert('Created: ' + JSON.stringify(res.data))
  }
  return (
    <div className="max-w-md mx-auto">
      <h1>Create Category</h1>
      <input value={name} onChange={e => setName(e.target.value)} />
      <button onClick={create}>Create</button>
    </div>
  )
}
export default AdminCategoryCreate