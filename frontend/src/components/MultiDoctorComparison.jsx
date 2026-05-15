import React, { useState } from 'react';
import { aiService } from '../api';
import { Stethoscope, AlertCircle, Loader2, ArrowRight } from 'lucide-react';

const MultiDoctorComparison = ({ records }) => {
    const [summary, setSummary] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    // Find if there are multiple records from different doctors
    // Group records by symptom overlap or category
    // For simplicity, we just look for ANY 2 records with different doctor_names
    const recordsWithDoctors = records.filter(r => r.doctor_name && r.doctor_name.trim() !== '');
    const uniqueDoctors = [...new Set(recordsWithDoctors.map(r => r.doctor_name))];

    if (uniqueDoctors.length < 2) {
        return null; // Not enough doctors to compare
    }

    // Pick the two most recent distinct records
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
        } catch (err) {
            setError('Failed to generate comparison. Please try again later.');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div style={{ backgroundColor: '#fff', borderRadius: '12px', padding: '20px', border: '1px solid #e2e8f0', marginBottom: '24px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                <div style={{ backgroundColor: '#fee2e2', padding: '8px', borderRadius: '50%' }}>
                    <Stethoscope size={24} color="#ef4444" />
                </div>
                <div>
                    <h3 style={{ fontSize: '18px', fontWeight: 'bold', margin: 0, color: '#1e293b' }}>Second Opinion Analysis</h3>
                    <p style={{ fontSize: '14px', color: '#64748b', margin: 0 }}>Detected prescriptions from multiple doctors.</p>
                </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', backgroundColor: '#f8fafc', padding: '16px', borderRadius: '8px', marginBottom: '16px' }}>
                <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontWeight: '600', color: '#0f172a' }}>{record1.doctor_name}</div>
                    <div style={{ fontSize: '12px', color: '#64748b' }}>{new Date(record1.date).toLocaleDateString()}</div>
                </div>
                <ArrowRight size={20} color="#94a3b8" />
                <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontWeight: '600', color: '#0f172a' }}>{record2.doctor_name}</div>
                    <div style={{ fontSize: '12px', color: '#64748b' }}>{new Date(record2.date).toLocaleDateString()}</div>
                </div>
            </div>

            {!summary && !isLoading && (
                <button 
                    onClick={handleCompare}
                    style={{ width: '100%', padding: '12px', backgroundColor: '#3b82f6', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: '600', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
                >
                    <AlertCircle size={18} />
                    Generate Discrepancy Summary
                </button>
            )}

            {isLoading && (
                <div style={{ textAlign: 'center', padding: '20px' }}>
                    <Loader2 size={24} color="#3b82f6" style={{ animation: 'spin 1s linear infinite', margin: '0 auto' }} />
                    <p style={{ color: '#64748b', marginTop: '8px', fontSize: '14px' }}>Analyzing medical decisions...</p>
                </div>
            )}

            {error && (
                <div style={{ backgroundColor: '#fef2f2', color: '#b91c1c', padding: '12px', borderRadius: '8px', fontSize: '14px', marginTop: '12px' }}>
                    {error}
                </div>
            )}

            {summary && (
                <div style={{ marginTop: '16px', borderTop: '1px solid #e2e8f0', paddingTop: '16px' }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '600', color: '#1e293b', marginBottom: '8px' }}>AI Discrepancy Summary:</h4>
                    <div style={{ fontSize: '14px', color: '#334155', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
                        {summary}
                    </div>
                </div>
            )}
        </div>
    );
};

export default MultiDoctorComparison;
