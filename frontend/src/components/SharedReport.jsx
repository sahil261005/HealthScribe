import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Pill, AlertTriangle, Activity, Calendar, Stethoscope, Loader2 } from 'lucide-react';

const SharedReport = ({ token }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const fetchReport = async () => {
            try {
                // Determine the backend URL directly since this doesn't use the authenticated api instance
                const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/';
                const response = await axios.get(`${apiUrl}share/${token}/`);
                setData(response.data);
            } catch (err) {
                setError(err.response?.data?.message || 'Failed to load report. Link may be invalid or expired.');
            } finally {
                setLoading(false);
            }
        };
        fetchReport();
    }, [token]);

    if (loading) {
        return (
            <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f9fafb' }}>
                <Loader2 size={40} className="animate-spin" color="#3b82f6" />
                <p style={{ marginTop: '16px', color: '#6b7280' }}>Loading secure medical report...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#f9fafb' }}>
                <div style={{ padding: '32px', backgroundColor: 'white', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)', textAlign: 'center', maxWidth: '400px' }}>
                    <AlertTriangle size={48} color="#ef4444" style={{ margin: '0 auto 16px' }} />
                    <h2 style={{ fontSize: '20px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>Access Denied</h2>
                    <p style={{ color: '#6b7280' }}>{error}</p>
                </div>
            </div>
        );
    }

    // Extract all unique allergies and active medicines from the records
    const allAllergies = [...new Set(data.records.flatMap(r => r.allergies))];
    // For simplicity, just grab the latest medicines
    const latestRecord = data.records.length > 0 ? data.records[data.records.length - 1] : null;

    return (
        <div style={{ minHeight: '100vh', backgroundColor: '#f3f4f6', padding: '32px 16px' }}>
            <div style={{ maxWidth: '800px', margin: '0 auto', backgroundColor: 'white', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)' }}>
                {/* Header */}
                <div style={{ backgroundColor: '#1f2937', color: 'white', padding: '32px', textAlign: 'center' }}>
                    <div style={{ width: '64px', height: '64px', backgroundColor: '#3b82f6', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', fontSize: '24px', fontWeight: 'bold' }}>
                        {data.patient_name.charAt(0).toUpperCase()}
                    </div>
                    <h1 style={{ fontSize: '28px', fontWeight: 'bold', margin: 0 }}>{data.patient_name}'s Health Summary</h1>
                    <p style={{ color: '#9ca3af', marginTop: '8px' }}>Consolidated Medical Profile</p>
                </div>

                {/* Warning Section */}
                {allAllergies.length > 0 && (
                    <div style={{ backgroundColor: '#fef2f2', borderLeft: '4px solid #ef4444', padding: '16px 24px', display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                        <AlertTriangle size={24} color="#ef4444" style={{ flexShrink: 0, marginTop: '2px' }} />
                        <div>
                            <h3 style={{ color: '#991b1b', fontWeight: '600', margin: '0 0 4px 0' }}>Known Allergies</h3>
                            <p style={{ color: '#b91c1c', margin: 0 }}>{allAllergies.join(', ')}</p>
                        </div>
                    </div>
                )}

                {/* Content */}
                <div style={{ padding: '32px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px', marginBottom: '32px' }}>
                        
                        {/* Current Meds */}
                        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '20px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                                <Pill size={20} color="#3b82f6" />
                                <h3 style={{ fontSize: '18px', fontWeight: '600', margin: 0 }}>Recent Medications</h3>
                            </div>
                            {latestRecord && latestRecord.medicines.length > 0 ? (
                                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                                    {latestRecord.medicines.map((med, i) => (
                                        <li key={i} style={{ padding: '12px 0', borderBottom: i < latestRecord.medicines.length - 1 ? '1px solid #f3f4f6' : 'none', display: 'flex', justifyContent: 'space-between' }}>
                                            <span style={{ fontWeight: '500', color: '#374151' }}>{med.name}</span>
                                            <span style={{ color: '#6b7280', fontSize: '14px' }}>{med.dosage}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p style={{ color: '#9ca3af' }}>No recent medications listed.</p>
                            )}
                        </div>

                        {/* Recent Vitals */}
                        <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '20px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                                <Activity size={20} color="#10b981" />
                                <h3 style={{ fontSize: '18px', fontWeight: '600', margin: 0 }}>Latest Vitals</h3>
                            </div>
                            {latestRecord && latestRecord.vitals.length > 0 ? (
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    {latestRecord.vitals.map((v, i) => (
                                        <div key={i} style={{ backgroundColor: '#f9fafb', padding: '12px', borderRadius: '8px', textAlign: 'center' }}>
                                            <div style={{ fontSize: '12px', color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{v.name}</div>
                                            <div style={{ fontSize: '16px', fontWeight: '600', color: '#111827', marginTop: '4px' }}>{v.value}</div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p style={{ color: '#9ca3af' }}>No recent vitals listed.</p>
                            )}
                        </div>
                    </div>

                    {/* Timeline */}
                    <h3 style={{ fontSize: '20px', fontWeight: 'bold', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Calendar size={20} color="#6366f1" />
                        Medical History
                    </h3>
                    
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {data.records.slice().reverse().map((record) => (
                            <div key={record.id} style={{ padding: '20px', border: '1px solid #e5e7eb', borderRadius: '12px', backgroundColor: '#f9fafb' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                                    <div>
                                        <h4 style={{ fontWeight: '600', fontSize: '16px', color: '#111827', margin: '0 0 4px 0' }}>{record.category}</h4>
                                        <p style={{ color: '#6b7280', fontSize: '14px', margin: 0 }}>
                                            {new Date(record.date).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
                                        </p>
                                    </div>
                                    {record.doctor_name && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', backgroundColor: '#e0e7ff', color: '#4338ca', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: '500' }}>
                                            <Stethoscope size={14} />
                                            {record.doctor_name}
                                        </div>
                                    )}
                                </div>
                                
                                {record.symptoms.length > 0 && (
                                    <div style={{ marginTop: '12px' }}>
                                        <span style={{ fontSize: '14px', color: '#6b7280', fontWeight: '500' }}>Symptoms: </span>
                                        <span style={{ fontSize: '14px', color: '#374151' }}>{record.symptoms.join(', ')}</span>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SharedReport;
