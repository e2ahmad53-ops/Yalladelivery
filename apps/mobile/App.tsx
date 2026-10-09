import React, { useEffect, useRef, useState } from 'react';
import { Alert, AppState, Linking, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import * as Location from 'expo-location';
import * as SecureStore from 'expo-secure-store';

declare const process: { env: Record<string, string | undefined> };
type User = {id:string; name:string; role:string; region:string; online:number};
type Order = {id:string; status:string; captain_id:string|null; customer_name?:string; phone?:string; address:string; fee:number; commission:number; route_group:string; notes?:string; scheduled_at:number};
type Message = {id:string; body:string; sender_name:string; created_at:number};
type Thread = {id:string; kind:string; owner_name:string; last_message:string|null};
type Wallet = {balance:number; reserved:number; available:number; entries:{id:string; amount:number; kind:string; created_at:number}[]};
type Position = {lat:number|null; lng:number|null; name:string; location_at:number|null; order_id?:string};
type PendingTransfer = {recipient_phone:string; amount:number; idempotency_key:string};
const API = (process.env.EXPO_PUBLIC_API_URL || '').replace(/\/$/, '');
const ROLE = process.env.EXPO_PUBLIC_APP_ROLE || 'store';
const money = (fils:number) => (fils/1000).toFixed(3)+' د.أ';
const statuses:Record<string,string> = {pending:'بانتظار كابتن', accepted:'تم القبول', picked_up:'في الطريق', delivered:'تم التسليم', cancelled:'ملغي'};
const ledgerNames:Record<string,string> = {opening:'رصيد افتتاحي',transfer:'تحويل رصيد',commission:'عمولة طلب',credit:'شحن من الإدارة'};
class HTTPError extends Error { constructor(public status:number,message:string){super(message);} }
const key = () => Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2);
const confirmAction = (message:string):Promise<boolean> => new Promise(resolve => Alert.alert('تأكيد',message,[{text:'رجوع',style:'cancel',onPress:()=>resolve(false)},{text:'تأكيد',onPress:()=>resolve(true)}],{cancelable:false}));

function Field({label,value,onChangeText,secret=false,numeric=false}: {label:string;value:string;onChangeText:(value:string)=>void;secret?:boolean;numeric?:boolean}) {
  return <View style={styles.field}><Text style={styles.label}>{label}</Text><TextInput accessibilityLabel={label} style={styles.input} value={value} onChangeText={onChangeText} secureTextEntry={secret} autoCapitalize="none" keyboardType={numeric?'decimal-pad':'default'}/></View>;
}
function Button({title,onPress,disabled=false,secondary=false}:{title:string;onPress:()=>void;disabled?:boolean;secondary?:boolean}) {
  return <TouchableOpacity accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button,secondary&&styles.secondary,disabled&&{opacity:.45}]}><Text style={[styles.buttonText,secondary&&{color:'#242833'}]}>{title}</Text></TouchableOpacity>;
}

export default function App(){
  const [token,setToken]=useState(''),[user,setUser]=useState<User|null>(null),[tab,setTab]=useState('orders');
  const [phone,setPhone]=useState(''),[password,setPassword]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  const [orders,setOrders]=useState<Order[]>([]),[wallet,setWallet]=useState<Wallet|null>(null),[threads,setThreads]=useState<Thread[]>([]);
  const [selectedThread,setSelectedThread]=useState(''),[messages,setMessages]=useState<Message[]>([]),[body,setBody]=useState('');
  const [name,setName]=useState(''),[customerPhone,setCustomerPhone]=useState(''),[address,setAddress]=useState(''),[fee,setFee]=useState('2'),[route,setRoute]=useState(''),[notes,setNotes]=useState(''),[schedule,setSchedule]=useState('');
  const [recipient,setRecipient]=useState(''),[amount,setAmount]=useState(''),[sharing,setSharing]=useState(false),[track,setTrack]=useState<Position|null>(null);
  const busyRef=useRef(false),refreshRef=useRef(false),sessionRef=useRef(''),messageCount=useRef(0);
  const pendingTransferKey='yalla-pending-transfer';

  async function api<T>(path:string,data?:unknown,auth=token):Promise<T>{
    if(!API)throw Error('حدد عنوان الخادم EXPO_PUBLIC_API_URL أولاً');
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch(API+'/api'+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(auth?{Authorization:'Bearer '+auth}:{})},body:data===undefined?undefined:JSON.stringify(data),signal:controller.signal});
      const result=await response.json();
      if(!response.ok){if(response.status===401&&auth===sessionRef.current){sessionRef.current='';setToken('');setUser(null);setSharing(false);}throw new HTTPError(response.status,result.error||'تعذر الاتصال بالخادم');}return result;
    }catch(error){if(error instanceof Error&&error.name==='AbortError')throw Error('انتهت مهلة الاتصال؛ أعد المحاولة');throw error;}
    finally{clearTimeout(timeout);}
  }
  async function run(fn:()=>Promise<void>){if(busyRef.current)return;busyRef.current=true;setBusy(true);try{await fn();}catch(error){setNotice(error instanceof Error?error.message:'تعذر تنفيذ العملية');}finally{busyRef.current=false;setBusy(false);}}
  async function refresh(auth=token,account=user){
    if(!auth||!account||refreshRef.current)return;refreshRef.current=true;
    try{
      const [nextOrders,nextThreads,nextWallet]=await Promise.all([api<Order[]>('/orders',undefined,auth),api<Thread[]>('/threads',undefined,auth),account.role==='captain'?api<Wallet>('/wallet',undefined,auth):Promise.resolve(null)]);
      if(sessionRef.current!==auth)return;
      setOrders(nextOrders);setThreads(nextThreads);setWallet(nextWallet);
      if(track?.order_id){const active=nextOrders.some(o=>o.id===track.order_id&&['accepted','picked_up'].includes(o.status));if(active){const position=await api<Position>('/orders/'+track.order_id+'/tracking',undefined,auth);if(sessionRef.current===auth)setTrack({...position,order_id:track.order_id});}else setTrack(null);}
      if(selectedThread){const next=await api<Message[]>('/threads/'+selectedThread+'/messages',undefined,auth);if(sessionRef.current!==auth)return;if(next.length>messageCount.current&&messageCount.current>0)setNotice('وصلت رسالة جديدة');messageCount.current=next.length;setMessages(next);}
    }finally{refreshRef.current=false;}
  }
  useEffect(()=>{if(!token||!user)return;const timer=setInterval(()=>{if(AppState.currentState==='active')refresh().catch(e=>setNotice(e.message));},6000);return()=>clearInterval(timer);},[token,user,selectedThread,track?.order_id]);
  useEffect(()=>{
    if(!sharing||!token||user?.role!=='captain')return;
    let cancelled=false;let subscription:Location.LocationSubscription|undefined;
    (async()=>{
      const permission=await Location.requestForegroundPermissionsAsync();
      if(permission.status!=='granted')throw Error('اسمح بالموقع من إعدادات الهاتف');
      const watch=await Location.watchPositionAsync({accuracy:Location.Accuracy.Balanced,timeInterval:15000,distanceInterval:30},position=>{if(!cancelled&&AppState.currentState==='active')api('/location',{lat:position.coords.latitude,lng:position.coords.longitude}).catch(e=>setNotice(e.message));});
      if(cancelled)watch.remove();else subscription=watch;
    })().catch(e=>{if(!cancelled){setNotice(e.message);setSharing(false);}});
    return()=>{cancelled=true;subscription?.remove();};
  },[sharing,token]);

  async function login(){
    const result=await api<{token:string;user:User}>('/login',{phone,password},'');
    if(result.user.role!==ROLE){await api('/logout',{},result.token);throw Error('استخدم النسخة المناسبة لنوع حسابك');}
    sessionRef.current=result.token;setToken(result.token);setUser(result.user);setPassword('');setNotice('أهلاً '+result.user.name);await refresh(result.token,result.user);
  }
  async function logout(){await api('/logout',{});sessionRef.current='';setToken('');setUser(null);setOrders([]);setThreads([]);setMessages([]);setSelectedThread('');setWallet(null);setSharing(false);setTrack(null);}
  async function changeOrder(order:Order,status?:string){await api('/orders/'+order.id+(status?'/status':'/assign'),status?{status}:{});setNotice('تم تحديث الطلب');await refresh();}
  async function createOrder(){
    const scheduled=schedule?Date.parse(schedule):Date.now();if(!Number.isFinite(scheduled))throw Error('اكتب الموعد بصيغة 2026-10-10T14:00:00+03:00');
    await api('/orders',{customer_name:name,phone:customerPhone,address,fee:Math.round(Number(fee)*1000),route_group:route,notes,scheduled_at:Math.floor(scheduled/1000)});
    setName('');setCustomerPhone('');setAddress('');setNotes('');setSchedule('');setNotice('تم إرسال الطلب');setTab('orders');await refresh();
  }
  async function openChat(identity:string){setSelectedThread(identity);messageCount.current=0;const result=await api<Message[]>('/threads/'+identity+'/messages');setMessages(result);messageCount.current=result.length;setTab('chat');}
  async function sendMessage(){if(!selectedThread)throw Error('اختار محادثة أولاً');await api('/threads/'+selectedThread+'/messages',{body});setBody('');await openChat(selectedThread);}
  async function transfer(){
    if(!user)return;
    const value=Math.round(Number(amount)*1000);if(!Number.isSafeInteger(value)||value<=0)throw Error('اكتب مبلغاً صحيحاً');
    const storageKey=pendingTransferKey+'-'+user.id;
    const saved=await SecureStore.getItemAsync(storageKey);
    let pending:PendingTransfer=saved?JSON.parse(saved):{recipient_phone:recipient.trim(),amount:value,idempotency_key:key()};
    if(saved&&(pending.recipient_phone!==recipient.trim()||pending.amount!==value))throw Error('عملية سابقة لم يتأكد نجاحها؛ أعد نفس الرقم والمبلغ حتى نتأكد قبل تحويل جديد');
    if(!await confirmAction('تحويل '+money(value)+' إلى رقم '+recipient+'؟'))return;
    await SecureStore.setItemAsync(storageKey,JSON.stringify(pending));
    try{await api('/wallet/transfer',pending);}catch(error){if(error instanceof HTTPError&&[400,403,409].includes(error.status))await SecureStore.deleteItemAsync(storageKey);throw error;}
    await SecureStore.deleteItemAsync(storageKey);setRecipient('');setAmount('');setNotice('تم تحويل الرصيد');await refresh();
  }
  async function restoreTransfer(){if(!user)return;const saved=await SecureStore.getItemAsync(pendingTransferKey+'-'+user.id);if(!saved){setNotice('لا توجد عملية غير مؤكدة');return;}const value:PendingTransfer=JSON.parse(saved);setRecipient(value.recipient_phone);setAmount((value.amount/1000).toString());setNotice('أعد التحويل بنفس البيانات؛ الخادم يمنع تكرار الخصم');}
  const button=(title:string,fn:()=>Promise<void>,secondary=false)=><Button title={title} onPress={()=>run(fn)} disabled={busy} secondary={secondary}/>;
  const isCaptain=user?.role==='captain';

  return <SafeAreaView style={styles.screen}><ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
    <View style={styles.header}><Text style={styles.brand}>Yalla <Text style={{color:'#e42d42'}}>delivery</Text></Text><Text style={styles.sub}>{ROLE==='captain'?'تطبيق الكابتن':'تطبيق المتجر والمطعم'}</Text></View>
    {!!notice&&<Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text>}
    {!user?<View style={styles.card}><Text style={styles.title}>أهلاً في يلا دليفري</Text><Text style={styles.description}>سجل دخولك وخلّينا نبدأ الشغل.</Text><Field label="رقم الهاتف" value={phone} onChangeText={setPhone}/><Field label="كلمة المرور" value={password} onChangeText={setPassword} secret/>{button('تسجيل الدخول',login)}<Text style={styles.muted}>الحساب يصدر من إدارة يلا دليفري.</Text></View>:<>
      <View style={styles.row}><View><Text style={styles.title}>{user.name}</Text><Text style={styles.muted}>{user.region}</Text></View>{button('خروج',logout,true)}</View>
      <View style={styles.tabs}>{[['orders','الطلبات'],[isCaptain?'wallet':'new',isCaptain?'المحفظة':'طلب جديد'],['chat','المحادثات']].map(([id,label])=><Button key={id} title={label} onPress={()=>setTab(id)} secondary={tab!==id}/>)}</View>
      {tab==='orders'&&<>
        {isCaptain&&<View style={styles.card}><Text style={styles.section}>جاهز للطلبات؟</Text>{button(user.online?'إيقاف استقبال الطلبات':'أنا متاح للطلبات',async()=>{await api('/availability',{online:!user.online});setUser({...user,online:user.online?0:1});await refresh();})}<Button title={sharing?'إيقاف مشاركة موقعي':'مشاركة موقعي للتتبع'} onPress={()=>setSharing(!sharing)} secondary/><Text style={styles.muted}>التتبع يعمل أثناء فتح التطبيق. عند إغلاقه يظهر آخر موقع معروف.</Text></View>}
        {button('تحديث الطلبات',async()=>{await refresh();},true)}
        {!orders.length&&<Text style={styles.empty}>ما في طلبات حالياً.</Text>}
        {orders.map(order=><View style={styles.card} key={order.id}>
          <View style={styles.row}><Text style={styles.section}>{order.customer_name||'طلب متاح'}</Text><Text style={styles.badge}>{statuses[order.status]}</Text></View>
          <Text style={styles.description}>{order.address}</Text><Text style={styles.muted}>#{order.id.slice(0,8)} · {money(order.fee)} · الطريق: {order.route_group}</Text>
          {order.phone&&<Text style={styles.description}>هاتف الزبون: {order.phone}</Text>}{order.notes&&<Text style={styles.description}>{order.notes}</Text>}
          <Text style={styles.muted}>الموعد: {new Date(order.scheduled_at*1000).toLocaleString('ar-JO')}</Text>
          {isCaptain&&order.status==='pending'&&button('قبول الطلب',()=>changeOrder(order))}
          {isCaptain&&order.status==='accepted'&&button('استلمت من المتجر',()=>changeOrder(order,'picked_up'))}
          {isCaptain&&order.status==='picked_up'&&button('تم التسليم',async()=>{if(await confirmAction('تأكيد تسليم الطلب؟'))await changeOrder(order,'delivered');})}
          {!isCaptain&&order.status==='pending'&&button('إلغاء الطلب',()=>changeOrder(order,'cancelled'),true)}
          {['accepted','picked_up'].includes(order.status)&&button('شات الطلب',()=>openChat('order-'+order.id),true)}
          {!isCaptain&&['accepted','picked_up'].includes(order.status)&&button('تتبع الكابتن',async()=>{const position=await api<Position>('/orders/'+order.id+'/tracking');setTrack({...position,order_id:order.id});},true)}
        </View>)}
        {track&&<View style={styles.card}><Text style={styles.section}>{track.name}</Text><Text style={styles.muted}>{track.location_at?'آخر تحديث: '+new Date(track.location_at*1000).toLocaleString('ar-JO'):'الموقع لم يصل بعد'}</Text>{track.lat!==null&&track.lng!==null&&button('فتح الموقع على الخريطة',async()=>{await Linking.openURL('https://www.openstreetmap.org/?mlat='+track.lat+'&mlon='+track.lng+'#map=16/'+track.lat+'/'+track.lng);},true)}<Button title="إغلاق التتبع" onPress={()=>setTrack(null)} secondary/></View>}
      </>}
      {tab==='new'&&!isCaptain&&<View style={styles.card}><Text style={styles.title}>اطلب كابتن</Text><Field label="اسم الزبون" value={name} onChangeText={setName}/><Field label="هاتف الزبون" value={customerPhone} onChangeText={setCustomerPhone}/><Field label="عنوان التوصيل" value={address} onChangeText={setAddress}/><Field label="سعر التوصيل بالدينار" value={fee} onChangeText={setFee} numeric/><Field label="مجموعة الطريق (مثلاً: خلدا)" value={route} onChangeText={setRoute}/><Field label="ملاحظات الطلب" value={notes} onChangeText={setNotes}/><Field label="موعد مجدول اختياري: 2026-10-10T14:00:00+03:00" value={schedule} onChangeText={setSchedule}/>{button('إرسال الطلب',createOrder)}</View>}
      {tab==='wallet'&&isCaptain&&wallet&&<>
        <View style={styles.wallet}><Text style={styles.walletLabel}>رصيدك المتاح</Text><Text style={styles.walletAmount}>{money(wallet.available)}</Text><Text style={styles.walletLabel}>الإجمالي {money(wallet.balance)} · المحجوز {money(wallet.reserved)}</Text></View>
        <View style={styles.card}><Text style={styles.section}>تحويل لكابتن</Text><Field label="رقم هاتف الكابتن المستلم" value={recipient} onChangeText={setRecipient}/><Field label="المبلغ بالدينار" value={amount} onChangeText={setAmount} numeric/>{button('مراجعة وتأكيد التحويل',transfer)}{button('استرجاع تحويل غير مؤكد',restoreTransfer,true)}<Text style={styles.muted}>الرصيد المحجوز للعمولات غير متاح للتحويل.</Text></View>
        <Text style={styles.section}>حركات المحفظة</Text>{wallet.entries.map(entry=><View style={styles.card} key={entry.id}><Text style={styles.section}>{money(entry.amount)}</Text><Text style={styles.muted}>{ledgerNames[entry.kind]||entry.kind} · {new Date(entry.created_at*1000).toLocaleString('ar-JO')}</Text></View>)}
      </>}
      {tab==='chat'&&<>
        {button('تواصل مع الإدارة',async()=>{const thread=await api<{id:string}>('/support',{});await openChat(thread.id);await refresh();})}
        {threads.map(thread=><Button key={thread.id} title={(thread.kind==='support'?'دعم الإدارة':'شات طلب')+' · '+(thread.last_message||'افتح المحادثة')} onPress={()=>run(()=>openChat(thread.id))} secondary/>)}
        {!!selectedThread&&<View style={styles.card}><Text style={styles.section}>{selectedThread.startsWith('support')?'دعم الإدارة':'محادثة الطلب'}</Text>{messages.map(message=><View key={message.id} style={styles.message}><Text style={styles.muted}>{message.sender_name} · {new Date(message.created_at*1000).toLocaleTimeString('ar-JO')}</Text><Text style={styles.description}>{message.body}</Text></View>)}<Field label="الرسالة" value={body} onChangeText={setBody}/>{button('إرسال',sendMessage)}</View>}
      </>}
    </>}
    <Text style={styles.footer}>يلا دليفري · نسخة أولية للتجربة</Text>
  </ScrollView></SafeAreaView>;
}

const styles=StyleSheet.create({
  screen:{flex:1,backgroundColor:'#f5f5f7'},page:{padding:20,paddingBottom:50},header:{backgroundColor:'#1c2028',padding:24,borderRadius:18,marginBottom:18},brand:{fontSize:29,fontWeight:'900',color:'white'},sub:{color:'#bbc1cd',marginTop:6,textAlign:'right'},title:{fontSize:24,fontWeight:'800',color:'#222631',textAlign:'right'},section:{fontSize:17,fontWeight:'700',color:'#222631',textAlign:'right'},description:{fontSize:15,color:'#353b45',lineHeight:25,textAlign:'right',marginVertical:8},muted:{fontSize:12,color:'#747b88',lineHeight:20,textAlign:'right',marginVertical:6},card:{backgroundColor:'white',borderRadius:16,padding:20,marginVertical:10,borderWidth:1,borderColor:'#e4e5ea'},field:{marginVertical:9},label:{fontSize:13,fontWeight:'600',color:'#363d49',textAlign:'right',marginBottom:7},input:{borderWidth:1,borderColor:'#cdd1da',borderRadius:9,padding:13,fontSize:16,textAlign:'right',backgroundColor:'white',color:'#242833'},button:{backgroundColor:'#df2536',paddingVertical:13,paddingHorizontal:16,borderRadius:10,marginVertical:5},buttonText:{fontSize:15,fontWeight:'700',color:'white',textAlign:'center'},secondary:{backgroundColor:'#e9ebf0'},row:{flexDirection:'row-reverse',justifyContent:'space-between',alignItems:'center',gap:10,flexWrap:'wrap'},tabs:{flexDirection:'row-reverse',gap:7,flexWrap:'wrap',marginVertical:12},notice:{backgroundColor:'#fff0d8',color:'#65491b',padding:13,borderRadius:10,lineHeight:22,textAlign:'right',marginBottom:12},badge:{backgroundColor:'#f0f1f5',padding:8,borderRadius:9,fontSize:12,color:'#505867'},empty:{textAlign:'center',color:'#757d89',padding:30},wallet:{backgroundColor:'#1e2430',padding:25,borderRadius:17,marginVertical:12},walletLabel:{color:'#c4cad5',textAlign:'right',lineHeight:24},walletAmount:{color:'white',fontSize:38,fontWeight:'800',textAlign:'right',marginVertical:12},message:{backgroundColor:'#f0f2f6',borderRadius:10,padding:12,marginVertical:6},footer:{color:'#9097a3',textAlign:'center',fontSize:12,marginTop:25}
});
