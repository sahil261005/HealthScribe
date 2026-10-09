// some doctor names already start with "Dr." (that's how they're written on the
// prescription) so only add it when it's missing, otherwise we show "Dr. Dr. Shah"
export const formatDoctorName = (name) => {
    if (!name) return '';
    const trimmed = name.trim();
    if (/^dr\b/i.test(trimmed)) return trimmed;
    return `Dr. ${trimmed}`;
};
