// webapp-frontend/src/pages/NewsDetail.tsx
import React, {useEffect,useState} from "react";
import { useParams } from "react-router-dom";
import api from "../services/api";

export default function NewsDetail(){
  const { id } = useParams();
  const [item,setItem]=useState<any>(null);
  useEffect(()=>{ (async()=>{ const r = await api.get(`/api/news/${id}`); setItem(r.data||r) })() },[id]);
  if(!item) return <div>Загрузка...</div>;
  return <div className="container">
    <div className="app-header"><h1 style={{margin:'0 auto'}}>{item.title}</h1></div>
    <div style={{marginTop:12}} className="card">
      {item.images && item.images.length>0 && <img src={item.images[0]} style={{width:'100%',height:220,objectFit:'cover',borderRadius:8}} />}
      <div style={{marginTop:8}} dangerouslySetInnerHTML={{__html: item.text}}/>
    </div>
  </div>;
}
