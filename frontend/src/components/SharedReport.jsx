import React, { useState, useEffect } from 'react';
import axios from 'axios';

const SharedReport = ({ token }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const fetchReport = async () => {
            try {
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
            <div className="shared-report-loading">
                <p className="shared-report-loading-text">Loading medical report...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="shared-report-error-wrapper">
                <div className="shared-report-error-card">
                    <h2 className="shared-report-error-title">Access Denied</h2>
                    <p className="shared-report-subtitle">{error}</p>
                </div>
            </div>
        );
    }

    const allAllergies = [...new Set(data.records.flatMap(r => r.allergies))];
    const latestRecord = data.records.length > 0 ? data.records[data.records.length - 1] : null;

    return (
        <div className="shared-report-page">
            <div className="shared-report-card">
                <div className="shared-report-header">
                    <div className="shared-report-avatar">
                        {data.patient_name.charAt(0).toUpperCase()}
                    </div>
                    <h1 className="shared-report-title">{data.patient_name}'s Health Summary</h1>
                    <p className="shared-report-subtitle">Consolidated Medical Profile</p>
                </div>

                {/* allergy warning banner */}
                {allAllergies.length > 0 && (
                    <div className="shared-report-allergies-banner">
                        <div>
                            <h3 className="shared-report-allergies-title">⚠ Known Allergies</h3>
                            <p className="shared-report-allergies-text">{allAllergies.join(', ')}</p>
                        </div>
                    </div>
                )}

                <div className="shared-report-content">
                    <div className="shared-report-grid">
                        
                        {/* recent medications */}
                        <div className="shared-report-box">
                            <div className="shared-report-box-title-row">
                                <h3 className="shared-report-box-title">Recent Medications</h3>
                            </div>
                            {latestRecord && latestRecord.medicines.length > 0 ? (
                                <ul className="shared-report-meds-list">
                                    {latestRecord.medicines.map((med, i) => (
                                        <li key={i} className="shared-report-med-item">
                                            <span className="shared-report-med-name">{med.name}</span>
                                            <span className="shared-report-med-dosage">{med.dosage}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="shared-report-subtitle">No recent medications listed.</p>
                            )}
                        </div>

                        {/* latest vitals */}
                        <div className="shared-report-box">
                            <div className="shared-report-box-title-row">
                                <h3 className="shared-report-box-title">Latest Vitals</h3>
                            </div>
                            {latestRecord && latestRecord.vitals.length > 0 ? (
                                <div className="shared-report-vitals-grid">
                                    {latestRecord.vitals.map((v, i) => (
                                        <div key={i} className="shared-report-vital-cell">
                                            <div className="shared-report-vital-name">{v.name}</div>
                                            <div className="shared-report-vital-value">{v.value}</div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p className="shared-report-subtitle">No recent vitals listed.</p>
                            )}
                        </div>
                    </div>

                    {/* medical history timeline */}
                    <h3 className="shared-report-timeline-title">
                        Medical History
                    </h3>
                    
                    <div className="shared-report-timeline-list">
                        {data.records.slice().reverse().map((record) => (
                            <div key={record.id} className="shared-report-timeline-card">
                                <div className="shared-report-timeline-header">
                                    <div>
                                        <h4 className="shared-report-timeline-cat">{record.category}</h4>
                                        <p className="shared-report-timeline-date">
                                            {new Date(record.date).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
                                        </p>
                                    </div>
                                    {record.doctor_name && (
                                        <span className="shared-report-doctor-badge">
                                            Dr. {record.doctor_name}
                                        </span>
                                    )}
                                </div>
                                
                                {record.symptoms.length > 0 && (
                                    <div className="shared-report-timeline-symptoms">
                                        <span className="shared-report-timeline-symptoms-label">Symptoms: </span>
                                        <span className="shared-report-timeline-symptoms-val">{record.symptoms.join(', ')}</span>
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
