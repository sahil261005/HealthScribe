import React, { useEffect, useState, useRef } from 'react';
import api from '../api';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import html2pdf from 'html2pdf.js';
import MultiDoctorComparison from './MultiDoctorComparison';

// custom tooltip for the doctor conflict chart
const ConflictTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="tooltip-container">
                <p className="tooltip-title">Symptom: {label}</p>
                {Object.keys(data.medicinesDetail || {}).map(doc => (
                    <div key={doc} className="tooltip-doctor-section">
                        <span className="tooltip-doctor-name">{doc}:</span>
                        <ul className="tooltip-medicines-list">
                            {data.medicinesDetail[doc].map((med, i) => (
                                <li key={i}>{med}</li>
                            ))}
                        </ul>
                    </div>
                ))}
            </div>
        );
    }
    return null;
};

// custom tooltip for the vitals trend chart
const VitalsTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="tooltip-container">
                <p className="tooltip-title">Visit Date: {label}</p>
                <p className="vitals-tooltip-doctor">
                    Consulting Doctor: {data.doctor}
                </p>
                <div className="vitals-tooltip-readings">
                    {data.SystolicBP && <div><span>Systolic BP:</span> <strong className="color-red">{data.SystolicBP} mmHg</strong></div>}
                    {data.DiastolicBP && <div><span>Diastolic BP:</span> <strong className="color-orange">{data.DiastolicBP} mmHg</strong></div>}
                    {data.Pulse && <div><span>Pulse / Heart Rate:</span> <strong className="color-green">{data.Pulse} bpm</strong></div>}
                    {data.Temperature && <div><span>Temperature:</span> <strong className="color-blue">{data.Temperature}°F</strong></div>}
                </div>
                <div className="vitals-tooltip-treatment">
                    <div className="vitals-tooltip-treatment-label">Prescribed Treatment:</div>
                    <div className="vitals-tooltip-treatment-value">{data.medicines}</div>
                </div>
            </div>
        );
    }
    return null;
};

const Dashboard = () => {
    const [allRecords, setAllRecords] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isExporting, setIsExporting] = useState(false);
    
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

    const handleDeleteRecord = async (id) => {
        if (window.confirm("Are you sure you want to delete this medical record?")) {
            try {
                await api.delete(`save_record/?id=${id}`);
                fetchAllRecords();
            } catch (error) {
                console.error("Failed to delete record:", error);
                alert("Failed to delete record.");
            }
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
                <p className="loading-text">Loading records...</p>
            </div>
        );
    }

    if (allRecords.length === 0) {
        return (
            <div className="dashboard-container">
                <h2 className="dashboard-title">Health Dashboard</h2>
                <div className="empty-state">
                    <h3 className="empty-title">No records yet</h3>
                    <p className="empty-text">Upload your first prescription to get started.</p>
                </div>
            </div>
        );
    }

    // compute some aggregate numbers for the summary
    const allMedicines = allRecords.flatMap(r => r.medicines.map(m => m.name));
    const uniqueMedicines = [...new Set(allMedicines)];
    
    const allAllergies = allRecords.flatMap(r => r.allergies);
    const uniqueAllergies = [...new Set(allAllergies)];
    
    const sortedRecords = [...allRecords].sort((a, b) => new Date(b.date) - new Date(a.date));
    const lastVisit = sortedRecords[0]?.date ? formatDate(sortedRecords[0].date) : 'N/A';

    // count how often each medicine shows up for the bar chart
    const medicineCounts = {};
    allMedicines.forEach(med => {
        medicineCounts[med] = (medicineCounts[med] || 0) + 1;
    });
    const chartData = Object.keys(medicineCounts)
        .map(name => ({ name, Count: medicineCounts[name] }))
        .sort((a, b) => b.Count - a.Count)
        .slice(0, 5);

    // build data for the doctor opinion conflict chart
    const symptomDocMap = {};
    const allDoctorsSet = new Set();

    allRecords.forEach(record => {
        const docName = record.doctor_name || 'Unspecified Doctor';
        
        record.medicines?.forEach(med => {
            const symptom = med.reason || 'General / Unspecified';
            allDoctorsSet.add(docName);
            
            if (!symptomDocMap[symptom]) {
                symptomDocMap[symptom] = {
                    symptom,
                    medicinesDetail: {}
                };
            }

            if (!symptomDocMap[symptom][docName]) {
                symptomDocMap[symptom][docName] = 0;
            }
            symptomDocMap[symptom][docName] += 1;

            if (!symptomDocMap[symptom].medicinesDetail[docName]) {
                symptomDocMap[symptom].medicinesDetail[docName] = [];
            }
            const medLabel = `${med.name}${med.dosage ? ` (${med.dosage})` : ''}`;
            if (!symptomDocMap[symptom].medicinesDetail[docName].includes(medLabel)) {
                symptomDocMap[symptom].medicinesDetail[docName].push(medLabel);
            }
        });
    });

    const conflictChartData = Object.values(symptomDocMap);
    const uniqueDoctors = Array.from(allDoctorsSet);

    // parse vitals from records into chart-friendly format
    const chronologicalRecords = [...allRecords].sort((a, b) => new Date(a.date) - new Date(b.date));

    const vitalsChartData = chronologicalRecords.map(record => {
        const dataPoint = {
            date: formatDate(record.date),
            doctor: record.doctor_name || 'Unspecified Doctor',
            medicines: record.medicines?.map(m => m.name).join(', ') || 'No medicines prescribed',
            symptoms: record.symptoms?.join(', ') || 'No symptoms reported'
        };

        record.vitals?.forEach(v => {
            const name = v.name.toLowerCase().trim();
            const val = v.value?.trim();
            if (!val) return;

            if (name === 'bp' || name === 'blood pressure') {
                const parts = val.split('/');
                if (parts.length === 2) {
                    const sys = parseInt(parts[0], 10);
                    const dia = parseInt(parts[1], 10);
                    if (!isNaN(sys)) dataPoint.SystolicBP = sys;
                    if (!isNaN(dia)) dataPoint.DiastolicBP = dia;
                } else {
                    const num = parseInt(val, 10);
                    if (!isNaN(num)) dataPoint.SystolicBP = num;
                }
            } else if (name === 'pulse' || name === 'heart rate' || name === 'hr') {
                const num = parseInt(val, 10);
                if (!isNaN(num)) dataPoint.Pulse = num;
            } else if (name === 'temp' || name === 'temperature') {
                const cleanedVal = val.replace(/[^\d.]/g, '');
                const num = parseFloat(cleanedVal);
                if (!isNaN(num)) dataPoint.Temperature = num;
            }
        });

        return dataPoint;
    }).filter(dp => dp.SystolicBP || dp.Pulse || dp.Temperature);

    const shareUrl = `${window.location.origin}/?token=${shareToken}`;
    const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(shareUrl)}`;

    return (
        <div className="dashboard-container">
            <div className="dashboard-header">
                <h2 className="dashboard-title">Health Dashboard</h2>
                
                <div className="nav-actions">
                    <button onClick={handleShareProfile} disabled={isSharing} className="btn-share-profile">
                        {isSharing ? 'Sharing...' : 'Share Profile'}
                    </button>

                    <button onClick={handleExportPDF} disabled={isExporting} className="btn-export">
                        {isExporting ? 'Exporting...' : 'Export PDF'}
                    </button>
                </div>
            </div>

            <div ref={dashboardRef}>
                {/* summary row */}
                <div className="dashboard-stats-grid">
                    <div className="dashboard-stat-card">
                        <div className="dashboard-stat-value">{allRecords.length}</div>
                        <div className="dashboard-stat-label">Total Records</div>
                    </div>
                    
                    <div className="dashboard-stat-card">
                        <div className="dashboard-stat-value">{uniqueMedicines.length}</div>
                        <div className="dashboard-stat-label">Medicines Prescribed</div>
                    </div>

                    <div className="dashboard-stat-card">
                        <div className="dashboard-stat-value">{uniqueAllergies.length}</div>
                        <div className="dashboard-stat-label">Known Allergies</div>
                    </div>

                    <div className="dashboard-stat-card">
                        <div className="dashboard-stat-value-text">{lastVisit}</div>
                        <div className="dashboard-stat-label">Last Visit</div>
                    </div>
                </div>

                {/* multi-doctor comparison (only shows if 2+ doctors) */}
                <MultiDoctorComparison records={sortedRecords} />

                {/* charts section */}
                <div className="charts-section">
                    
                    {/* doctor opinion conflict matrix */}
                    {conflictChartData.length > 0 && (
                        <div className="chart-card-container">
                            <div className="chart-card-header">
                                <h3 className="chart-card-title">Doctor Treatment Conflict Matrix</h3>
                                <p className="chart-card-description">
                                    What different doctors prescribed for each symptom.
                                </p>
                            </div>
                            <div className="chart-wrapper">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={conflictChartData} margin={{ top: 10, right: 20, left: -20, bottom: 5 }}>
                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                        <XAxis dataKey="symptom" tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
                                        <YAxis allowDecimals={false} tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} label={{ value: 'No. of Prescribed Drugs', angle: -90, position: 'insideLeft', offset: 0, style: { textAnchor: 'middle', fill: '#64748b', fontSize: 12, fontWeight: '500' } }} />
                                        <Tooltip content={<ConflictTooltip />} />
                                        <Legend verticalAlign="top" height={36} iconType="circle" />
                                        {uniqueDoctors.map((docName, idx) => (
                                            <Bar 
                                                key={docName} 
                                                dataKey={docName} 
                                                fill={idx === 0 ? "#1a8a6e" : idx === 1 ? "#2563eb" : idx === 2 ? "#d97706" : "#e11d48"} 
                                                radius={[4, 4, 0, 0]} 
                                                barSize={24}
                                            />
                                        ))}
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}

                    {/* vitals trend over time */}
                    {vitalsChartData.length > 0 && (
                        <div className="chart-card-container">
                            <div className="chart-card-header">
                                <h3 className="chart-card-title">Vitals Over Time</h3>
                                <p className="chart-card-description">
                                    Blood pressure, pulse, and temperature readings across visits.
                                </p>
                            </div>
                            <div className="chart-wrapper">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={vitalsChartData} margin={{ top: 10, right: 20, left: -20, bottom: 5 }}>
                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                        <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                                        <YAxis tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} label={{ value: 'Vital Readings', angle: -90, position: 'insideLeft', offset: 0, style: { textAnchor: 'middle', fill: '#64748b', fontSize: 12, fontWeight: '500' } }} />
                                        <Tooltip content={<VitalsTooltip />} />
                                        <Legend verticalAlign="top" height={36} iconType="plainline" />
                                        
                                        <Line type="monotone" dataKey="SystolicBP" stroke="#ef4444" strokeWidth={2.5} activeDot={{ r: 6 }} name="Systolic BP (mmHg)" dot={{ stroke: '#ef4444', strokeWidth: 2, r: 4, fill: '#fff' }} />
                                        <Line type="monotone" dataKey="DiastolicBP" stroke="#f97316" strokeWidth={2.5} name="Diastolic BP (mmHg)" dot={{ stroke: '#f97316', strokeWidth: 2, r: 4, fill: '#fff' }} />
                                        <Line type="monotone" dataKey="Pulse" stroke="#10b981" strokeWidth={2.5} name="Pulse (bpm)" dot={{ stroke: '#10b981', strokeWidth: 2, r: 4, fill: '#fff' }} />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}

                    {/* most frequent medications bar chart */}
                    {chartData.length > 0 && (
                        <div className="chart-card-container">
                            <div className="chart-card-header">
                                <h3 className="chart-card-title">Most Frequent Medications</h3>
                                <p className="chart-card-description">Top 5 most prescribed medications.</p>
                            </div>
                            <div className="chart-wrapper-short">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                        <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
                                        <YAxis allowDecimals={false} tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
                                        <Tooltip cursor={{ fill: '#f8fafc' }} contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }} />
                                        <Bar dataKey="Count" fill="#3b82f6" radius={[4, 4, 0, 0]} barSize={36} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}
                </div>

                {/* timeline of all records */}
                <div className="timeline-section">
                    <h3 className="timeline-title">Medical Timeline</h3>
                    <div className="timeline-list">
                        {sortedRecords.map((record, index) => (
                            <div key={record.id} className="timeline-item">
                                <div className="timeline-item-spine">
                                    <div className="timeline-item-dot"></div>
                                    {index !== sortedRecords.length - 1 && (
                                        <div className="timeline-item-line"></div>
                                    )}
                                </div>
                                
                                <div className="timeline-card">
                                    <div className="timeline-card-header">
                                        <div>
                                            <h4 className="timeline-card-title">{record.category}</h4>
                                            <p className="timeline-card-date">{formatDate(record.date)}</p>
                                        </div>
                                        <div className="timeline-header-actions">
                                            {record.doctor_name && (
                                                <span className="timeline-doctor-badge">
                                                    Dr. {record.doctor_name}
                                                </span>
                                            )}
                                            <button 
                                                onClick={() => handleDeleteRecord(record.id)} 
                                                className="btn-delete-record"
                                                title="Delete this record"
                                            >
                                                Delete
                                            </button>
                                        </div>
                                    </div>

                                    {record.symptoms?.length > 0 && (
                                        <div className="timeline-symptoms">
                                            <span className="timeline-symptoms-label">Symptoms: </span>
                                            <span className="timeline-symptoms-text">{record.symptoms.join(', ')}</span>
                                        </div>
                                    )}

                                    {record.medicines?.length > 0 && (
                                        <div className="timeline-prescriptions">
                                            <div className="timeline-prescriptions-title">
                                                Prescriptions
                                            </div>
                                            <ul className="timeline-prescriptions-list">
                                                {record.medicines.map((med, i) => (
                                                    <li key={i}>{med.name} <span className="timeline-prescription-dosage">{med.dosage ? `(${med.dosage})` : ''}</span></li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}

                                    {((record.vitals?.some(v => v.value)) || (record.allergies?.length > 0)) && (
                                        <div className="timeline-tags-row">
                                            {record.vitals?.filter(v => v.value).map((v, i) => (
                                                <span key={`v-${i}`} className="timeline-tag-vital">
                                                    {v.name}: {v.value}
                                                </span>
                                            ))}
                                            {record.allergies?.map((a, i) => (
                                                <span key={`a-${i}`} className="timeline-tag-allergy">
                                                    ⚠ {a}
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

            {/* share modal with QR code */}
            {shareModalOpen && (
                <div className="modal-overlay">
                    <div className="modal-container modal-container-small">
                        <div className="modal-close-row">
                            <button onClick={() => setShareModalOpen(false)} className="btn-close">✕</button>
                        </div>
                        <h2 className="modal-share-title">Share Health Profile</h2>
                        <p className="modal-share-description">Scan the QR code or copy the link to share your medical history.</p>
                        
                        <div className="modal-qr-container">
                            <img src={qrCodeUrl} alt="QR Code" className="modal-qr-image" />
                        </div>

                        <div className="modal-input-row">
                            <input type="text" value={shareUrl} readOnly className="modal-share-input" />
                            <button onClick={() => { navigator.clipboard.writeText(shareUrl); alert('Copied!'); }} className="btn-copy">
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
