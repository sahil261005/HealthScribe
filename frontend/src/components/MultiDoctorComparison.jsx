import React, { useState } from 'react';
import { aiService } from '../api';

const MultiDoctorComparison = ({ records }) => {
    const [summary, setSummary] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    // only show if we have records from at least 2 different doctors
    const recordsWithDoctors = records.filter(r => r.doctor_name && r.doctor_name.trim() !== '');
    const uniqueDoctors = [...new Set(recordsWithDoctors.map(r => r.doctor_name))];

    if (uniqueDoctors.length < 2) {
        return null;
    }

    // pick the two most recent records from different doctors
    let record1 = null;
    let record2 = null;

    for (let r of [...recordsWithDoctors].reverse()) {
        if (!record1) {
            record1 = r;
        } else if (!record2 && r.doctor_name !== record1.doctor_name) {
            record2 = r;
            break;
        }
    }

    if (!record1 || !record2) return null;

    const handleCompare = async () => {
        setIsLoading(true);
        setError('');
        try {
            const response = await aiService.post('/compare_doctors', {
                record1: record1,
                record2: record2
            });
            setSummary(response.data.summary);
        } catch {
            setError('Failed to generate comparison. Please try again later.');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="comparison-card">
            <div className="comparison-header">
                <div>
                    <h3 className="comparison-title">Second Opinion Analysis</h3>
                    <p className="comparison-subtitle">Detected prescriptions from multiple doctors.</p>
                </div>
            </div>

            <div className="comparison-doctors-row">
                <div className="comparison-doctor-col">
                    <div className="comparison-doctor-name">{record1.doctor_name}</div>
                    <div className="comparison-doctor-date">{new Date(record1.date).toLocaleDateString()}</div>
                </div>
                <span className="comparison-arrow">→</span>
                <div className="comparison-doctor-col">
                    <div className="comparison-doctor-name">{record2.doctor_name}</div>
                    <div className="comparison-doctor-date">{new Date(record2.date).toLocaleDateString()}</div>
                </div>
            </div>

            {!summary && !isLoading && (
                <button 
                    onClick={handleCompare}
                    className="btn-generate-summary"
                >
                    Generate Comparison
                </button>
            )}

            {isLoading && (
                <div className="comparison-loader">
                    <p className="comparison-loader-text">Analyzing prescriptions...</p>
                </div>
            )}

            {error && (
                <div className="comparison-error">
                    {error}
                </div>
            )}

            {summary && (
                <div className="comparison-summary-container">
                    <h4 className="comparison-summary-title">Comparison Summary:</h4>
                    <div className="comparison-summary-text">
                        {summary}
                    </div>
                </div>
            )}
        </div>
    );
};

export default MultiDoctorComparison;

