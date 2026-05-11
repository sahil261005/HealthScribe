import React, { useEffect, useState, useRef } from 'react';
import api from '../api';
import { Calendar, Pill, Activity, AlertTriangle, FileText, Download, Share2, Loader2, X, Stethoscope } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import html2pdf from 'html2pdf.js';
import MultiDoctorComparison from './MultiDoctorComparison';

const Dashboard = () => {
    const [allRecords, setAllRecords] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isExporting, setIsExporting] = useState(false);
    
    // Sharing state
    const [shareModalOpen, setShareModalOpen] = useState(false);
    const [shareToken, setShareToken] = useState('');
    const [isSharing, setIsSharing] = useState(false);

    const dashboardRef = useRef(null);

    useEffect(() => {
        fetchAllRecords();
    }, []);

    const fetchAllRecords = async () => {
        setIsLoading(true);
        try {
            const response = await api.get('save_record/');
            setAllRecords(response.data);
        } catch (error) {
            console.error('Failed to fetch records:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const formatDate = (dateString) => {
        const dateObject = new Date(dateString);
        return dateObject.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric', 
            year: 'numeric' 
        });
    };

    const handleExportPDF = () => {
        setIsExporting(true);
        const element = dashboardRef.current;
        const options = {
            margin:       10,
            filename:     'HealthScribe_History.pdf',
            image:        { type: 'jpeg', quality: 0.98 },
            html2canvas:  { scale: 2, useCORS: true },
            jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
        };
        html2pdf().from(element).set(options).save()
            .then(() => setIsExporting(false))
            .catch(() => setIsExporting(false));
    };

    const handleShareProfile = async () => {
        setIsSharing(true);
        try {
            const response = await api.post('share/generate/');
            setShareToken(response.data.token);
            setShareModalOpen(true);
        } catch (error) {
            console.error("Failed to generate share link", error);
            alert("Failed to generate share link");
        } finally {
            setIsSharing(false);
        }
    };

    if (isLoading) {
        return (
            <div className="dashboard-container">
                <h2 className="dashboard-title">Health Dashboard</h2>
                <div className="skeleton-grid">
                    {[1, 2, 3].map((i) => <div key={i} className="skeleton-card"></div>)}
                </div>
            </div>
        );
    }

    if (allRecords.length === 0) {
        return (
            <div className="dashboard-container">
                <h2 className="dashboard-title">Health Dashboard</h2>
                <div className="empty-state">
                    <FileText size={48} color="#cbd5e1" />
                    <h3 className="empty-title">No Medical Records Yet</h3>
                    <p className="empty-text">Upload your first prescription or lab report to get started.</p>
                </div>
            </div>
        );
    }

    // --- Analytics Computations ---
    const allMedicines = allRecords.flatMap(r => r.medicines.map(m => m.name));
    const uniqueMedicines = [...new Set(allMedicines)];
    
    const allAllergies = allRecords.flatMap(r => r.allergies);
    const uniqueAllergies = [...new Set(allAllergies)];
    
    // Sort records chronologically (newest first)
    const sortedRecords = [...allRecords].sort((a, b) => new Date(b.date) - new Date(a.date));
    const lastVisit = sortedRecords[0]?.date ? formatDate(sortedRecords[0].date) : 'N/A';

    // Prepare data for Medicine Frequency Chart
    const medicineCounts = {};
    allMedicines.forEach(med => {
        medicineCounts[med] = (medicineCounts[med] || 0) + 1;
    });
    const chartData = Object.keys(medicineCounts)
        .map(name => ({ name, Count: medicineCounts[name] }))
        .sort((a, b) => b.Count - a.Count)
        .slice(0, 5); // top 5

    const shareUrl = `${window.location.origin}/?token=${shareToken}`;
    const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(shareUrl)}`;

    return (
        <div className="dashboard-container">
            {/* Header */}
            <div className="dashboard-header" style={{ marginBottom: '24px' }}>
                <div>
                    <h2 className="dashboard-title">Health Dashboard</h2>
                    <p style={{ color: '#64748b', margin: 0, fontSize: '14px' }}>Your medical history at a glance</p>
                </div>
                
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button onClick={handleShareProfile} disabled={isSharing} className="btn-upload" style={{ backgroundColor: '#10b981', color: 'white' }}>
                        {isSharing ? <Loader2 size={18} className="animate-spin" /> : <Share2 size={18} />}
                        Share Profile
                    </button>

                    <button onClick={handleExportPDF} disabled={isExporting} className="btn-export">
                        {isExporting ? <Loader2 size={18} className="animate-spin" /> : <Download size={18} />}
                        Export PDF
                    </button>
                </div>
            </div>

            <div ref={dashboardRef}>
                {/* Summary Cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                    <div style={{ backgroundColor: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ backgroundColor: '#eff6ff', padding: '12px', borderRadius: '50%' }}>
                            <FileText size={24} color="#3b82f6" />
                        </div>
                        <div>
                            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#1e293b' }}>{allRecords.length}</div>
                            <div style={{ fontSize: '14px', color: '#64748b' }}>Total Records</div>
                        </div>
                    </div>
                    
                    <div style={{ backgroundColor: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ backgroundColor: '#ecfdf5', padding: '12px', borderRadius: '50%' }}>
                            <Pill size={24} color="#10b981" />
                        </div>
                        <div>
                            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#1e293b' }}>{uniqueMedicines.length}</div>
                            <div style={{ fontSize: '14px', color: '#64748b' }}>Medicines Prescribed</div>
                        </div>
                    </div>

                    <div style={{ backgroundColor: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ backgroundColor: '#fef2f2', padding: '12px', borderRadius: '50%' }}>
                            <AlertTriangle size={24} color="#ef4444" />
                        </div>
                        <div>
                            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#1e293b' }}>{uniqueAllergies.length}</div>
                            <div style={{ fontSize: '14px', color: '#64748b' }}>Known Allergies</div>
                        </div>
                    </div>

                    <div style={{ backgroundColor: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ backgroundColor: '#f8fafc', padding: '12px', borderRadius: '50%' }}>
                            <Calendar size={24} color="#64748b" />
                        </div>
                        <div>
                            <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#1e293b' }}>{lastVisit}</div>
                            <div style={{ fontSize: '14px', color: '#64748b' }}>Last Visit</div>
                        </div>
                    </div>
                </div>

                {/* AI Multi-Doctor Comparison */}
                <MultiDoctorComparison records={sortedRecords} />

                {/* Analytics Chart */}
                {chartData.length > 0 && (
                    <div style={{ backgroundColor: '#fff', padding: '24px', borderRadius: '12px', border: '1px solid #e2e8f0', marginBottom: '24px' }}>
                        <h3 style={{ fontSize: '18px', fontWeight: 'bold', color: '#1e293b', marginBottom: '16px' }}>Most Frequent Medications</h3>
                        <div style={{ width: '100%', height: '250px' }}>
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                    <XAxis dataKey="name" tick={{fill: '#64748b', fontSize: 12}} axisLine={false} tickLine={false} />
                                    <YAxis allowDecimals={false} tick={{fill: '#64748b', fontSize: 12}} axisLine={false} tickLine={false} />
                                    <Tooltip cursor={{fill: '#f8fafc'}} contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)'}} />
                                    <Bar dataKey="Count" fill="#3b82f6" radius={[4, 4, 0, 0]} barSize={40} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                )}

                {/* Timeline View */}
                <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 'bold', color: '#1e293b', marginBottom: '16px' }}>Medical Timeline</h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {sortedRecords.map((record, index) => (
                            <div key={record.id} style={{ display: 'flex', gap: '16px' }}>
                                {/* Timeline Line & Dot */}
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                    <div style={{ width: '16px', height: '16px', borderRadius: '50%', backgroundColor: '#3b82f6', border: '4px solid #eff6ff', zIndex: 1 }}></div>
                                    {index !== sortedRecords.length - 1 && (
                                        <div style={{ width: '2px', flexGrow: 1, backgroundColor: '#e2e8f0', margin: '-4px 0' }}></div>
                                    )}
                                </div>
                                
                                {/* Card Content */}
                                <div style={{ flex: 1, backgroundColor: '#fff', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0', marginBottom: index !== sortedRecords.length - 1 ? '16px' : '0' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                                        <div>
                                            <h4 style={{ fontSize: '16px', fontWeight: 'bold', color: '#0f172a', margin: '0 0 4px 0' }}>{record.category}</h4>
                                            <p style={{ fontSize: '14px', color: '#64748b', margin: 0 }}>{formatDate(record.date)}</p>
                                        </div>
                                        {record.doctor_name && (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', backgroundColor: '#f1f5f9', color: '#475569', padding: '4px 8px', borderRadius: '6px', fontSize: '12px', fontWeight: '500' }}>
                                                <Stethoscope size={14} />
                                                {record.doctor_name}
                                            </div>
                                        )}
                                    </div>

                                    {record.symptoms?.length > 0 && (
                                        <div style={{ marginBottom: '12px' }}>
                                            <span style={{ fontSize: '14px', fontWeight: '500', color: '#475569' }}>Symptoms: </span>
                                            <span style={{ fontSize: '14px', color: '#1e293b' }}>{record.symptoms.join(', ')}</span>
                                        </div>
                                    )}

                                    {record.medicines?.length > 0 && (
                                        <div style={{ marginBottom: '12px', padding: '12px', backgroundColor: '#f8fafc', borderRadius: '8px' }}>
                                            <div style={{ fontSize: '14px', fontWeight: '500', color: '#475569', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                <Pill size={14} /> Prescriptions
                                            </div>
                                            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '14px', color: '#1e293b' }}>
                                                {record.medicines.map((med, i) => (
                                                    <li key={i}>{med.name} <span style={{ color: '#64748b' }}>{med.dosage ? `(${med.dosage})` : ''}</span></li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}

                                    {((record.vitals?.some(v => v.value)) || (record.allergies?.length > 0)) && (
                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            {record.vitals?.filter(v => v.value).map((v, i) => (
                                                <span key={`v-${i}`} style={{ backgroundColor: '#ecfdf5', color: '#059669', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                    <Activity size={12} /> {v.name}: {v.value}
                                                </span>
                                            ))}
                                            {record.allergies?.map((a, i) => (
                                                <span key={`a-${i}`} style={{ backgroundColor: '#fef2f2', color: '#dc2626', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                    <AlertTriangle size={12} /> {a}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Share Modal */}
            {shareModalOpen && (
                <div className="modal-overlay">
                    <div className="modal-container" style={{ maxWidth: '400px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                            <button onClick={() => setShareModalOpen(false)} className="btn-close"><X size={20} /></button>
                        </div>
                        <h2 style={{ fontSize: '20px', fontWeight: 'bold', color: '#1e293b', marginBottom: '8px' }}>Share Health Profile</h2>
                        <p style={{ fontSize: '14px', color: '#64748b', marginBottom: '24px' }}>Scan the QR code or copy the link below to share your consolidated medical history.</p>
                        
                        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '24px' }}>
                            <img src={qrCodeUrl} alt="QR Code" style={{ width: '200px', height: '200px', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '8px' }} />
                        </div>

                        <div style={{ display: 'flex', gap: '8px' }}>
                            <input type="text" value={shareUrl} readOnly style={{ flex: 1, padding: '8px 12px', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '14px', backgroundColor: '#f8fafc', color: '#475569' }} />
                            <button onClick={() => { navigator.clipboard.writeText(shareUrl); alert('Copied!'); }} style={{ padding: '8px 16px', backgroundColor: '#3b82f6', color: 'white', borderRadius: '6px', border: 'none', fontWeight: '500', cursor: 'pointer' }}>
                                Copy
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
