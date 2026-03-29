import React, { useEffect, useState, useRef } from 'react';
import api from '../api';
import { Calendar, Pill, Activity, AlertTriangle, FileText, Download, Loader2 } from 'lucide-react';
import html2pdf from 'html2pdf.js';


const Dashboard = () => {
    const [allRecords, setAllRecords] = useState([]);
    const [recordsByCategory, setRecordsByCategory] = useState({});
    const [isLoading, setIsLoading] = useState(true);
    const [isExporting, setIsExporting] = useState(false);
    const dashboardRef = useRef(null);

    // fetch records when the component first loads
    useEffect(() => {
        fetchAllRecords();
    }, []);

    const fetchAllRecords = async () => {
        setIsLoading(true);
        try {
            const response = await api.get('save_record/');
            const recordsData = response.data;
            console.log("records loaded", recordsData.length);
            
            setAllRecords(recordsData);
            groupRecordsByCategory(recordsData);
            
        } catch (error) {
            console.error('Failed to fetch records:', error);
        } finally {
            setIsLoading(false);
        }
    };

    // groups records by their category so we can display them in sections
    const groupRecordsByCategory = (recordsList) => {
        const groupedRecords = {};

        for (let record of recordsList) {
            const categoryName = record.category || 'Uncategorized';
            
            if (!groupedRecords[categoryName]) {
                groupedRecords[categoryName] = [];
            }
            
            groupedRecords[categoryName].push(record);
        }

        setRecordsByCategory(groupedRecords);
    };

    const formatDate = (dateString) => {
        const dateObject = new Date(dateString);
        return dateObject.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric', 
            year: 'numeric' 
        });
    };

    const categoryNames = Object.keys(recordsByCategory);

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

    // loading skeleton while data is being fetched
    if (isLoading) {
        return (
            <div className="dashboard-container">
                <h2 className="dashboard-title">Health Dashboard</h2>
                <div className="skeleton-grid">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="skeleton-card"></div>
                    ))}
                </div>
            </div>
        );
    }

    // empty state - no records yet
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

    return (
        <div className="dashboard-container">
            {/* header with record count and export button */}
            <div className="dashboard-header">
                <div>
                    <h2 className="dashboard-title">Health Dashboard</h2>
                    <div className="dashboard-stats">
                        <span className="stat-pill stat-pill-blue">
                            {allRecords.length} Records
                        </span>
                        <span className="stat-pill stat-pill-purple">
                            {categoryNames.length} Categories
                        </span>
                    </div>
                </div>
                
                <button
                    onClick={handleExportPDF}
                    disabled={isExporting}
                    className="btn-export"
                >
                    {isExporting ? (
                        <>
                            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                            Exporting...
                        </>
                    ) : (
                        <>
                            <Download size={18} />
                            Export PDF
                        </>
                    )}
                </button>
            </div>
            
            {/* records grouped by category */}
            <div ref={dashboardRef} className="category-grid">
                {categoryNames.map((categoryName) => {
                    const recordsInCategory = recordsByCategory[categoryName];
                    
                    return (
                        <div 
                            key={categoryName} 
                            className="category-card"
                        >
                            <div className="category-header">
                                <h3 className="category-title">
                                    <FileText size={18} />
                                    {categoryName}
                                </h3>
                                <p className="category-count">{recordsInCategory.length} record(s)</p>
                            </div>
                            
                            <div className="record-list">
                                {recordsInCategory.map((record) => (
                                    <div 
                                        key={record.id} 
                                        className="record-item"
                                    >
                                        <p className="record-date">
                                            <Calendar size={12} />
                                            {formatDate(record.date)}
                                        </p>
                                        
                                        <div className="record-details">
                                            {record.symptoms?.length > 0 && (
                                                <div>
                                                    <span className="label-symptoms">Symptoms: </span>
                                                    <span>{record.symptoms.join(', ')}</span>
                                                </div>
                                            )}
                                            
                                            {record.medicines?.length > 0 && (
                                                <div>
                                                    <span className="label-medicines">Medicines:</span>
                                                    <ul className="medicine-list">
                                                        {record.medicines.map((medicine, index) => (
                                                            <li key={index}>
                                                                {medicine.name} {medicine.dosage && `(${medicine.dosage})`}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            
                                            {/* show vitals and allergies if they exist */}
                                            {((record.vitals?.some(v => v.value && v.value.trim() !== '')) || 
                                              (record.allergies?.length > 0)) && (
                                                <div className="vitals-row">
                                                    {record.vitals?.filter(v => v.value && v.value.trim() !== '').map((vital, index) => (
                                                        <span 
                                                            key={`vital-${index}`} 
                                                            className="vital-tag"
                                                        >
                                                            <Activity size={10} />
                                                            {vital.name}: {vital.value}
                                                        </span>
                                                    ))}

                                                    {record.allergies?.map((allergy, index) => (
                                                        <span 
                                                            key={`allergy-${index}`} 
                                                            className="allergy-tag"
                                                        >
                                                            <AlertTriangle size={10} />
                                                            {allergy}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default Dashboard;
