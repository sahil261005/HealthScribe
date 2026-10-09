import forms from '@tailwindcss/forms'
import containerQueries from '@tailwindcss/container-queries'

// this used to be inline in index.html for the tailwind CDN script.
// the CDN builds the css in the browser on every page load and isn't meant
// for production, so now tailwind is built with vite instead (same config)

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        'surface-container-lowest': '#ffffff',
        'tertiary-container': '#002113',
        'on-secondary': '#ffffff',
        'error': '#ba1a1a',
        'surface-variant': '#e0e3e5',
        'primary-container': '#131b2e',
        'surface-dim': '#d8dadc',
        'surface-bright': '#f7f9fb',
        'on-primary-container': '#7c839b',
        'surface': '#f7f9fb',
        'on-tertiary-container': '#009668',
        'on-error-container': '#93000a',
        'surface-tint': '#565e74',
        'primary-fixed-dim': '#bec6e0',
        'tertiary-fixed-dim': '#4edea3',
        'inverse-on-surface': '#eff1f3',
        'surface-container-highest': '#e0e3e5',
        'inverse-surface': '#2d3133',
        'on-tertiary': '#ffffff',
        'error-container': '#ffdad6',
        'background': '#f7f9fb',
        'surface-container-high': '#e6e8ea',
        'surface-container': '#eceef0',
        'surface-container-low': '#f2f4f6',
        'on-surface': '#191c1e',
        'on-primary': '#ffffff',
        'on-background': '#191c1e',
        'tertiary-fixed': '#6ffbbe',
        'outline': '#76777d',
        'secondary-container': '#316bf3',
        'primary-fixed': '#dae2fd',
        'on-surface-variant': '#45464d',
        'primary': '#000000',
        'on-primary-fixed': '#131b2e',
        'secondary-fixed': '#dbe1ff',
        'on-secondary-container': '#fefcff',
        'secondary': '#0051d5',
        'on-error': '#ffffff',
        'outline-variant': '#c6c6cd',
        'tertiary': '#000000'
      },
      borderRadius: {
        DEFAULT: '0.25rem',
        lg: '0.5rem',
        xl: '0.75rem',
        full: '9999px'
      },
      spacing: {
        'sidebar-width': '280px',
        'margin-desktop': '40px',
        'xs': '8px',
        'sm': '16px',
        'base': '4px',
        'margin-mobile': '16px',
        'md': '24px',
        'lg': '32px',
        'xl': '48px',
        'gutter': '24px'
      },
      fontFamily: {
        'body-lg': ['Inter'],
        'headline-lg': ['Inter'],
        'display-lg': ['Inter'],
        'body-md': ['Inter'],
        'label-sm': ['Geist'],
        'body-sm': ['Inter'],
        'label-md': ['Geist'],
        'headline-md': ['Inter'],
        'headline-sm': ['Inter']
      },
      fontSize: {
        'body-lg': ['18px', { lineHeight: '28px', fontWeight: '400' }],
        'headline-lg': ['32px', { lineHeight: '40px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-lg-mobile': ['28px', { lineHeight: '36px', fontWeight: '600' }],
        'display-lg': ['48px', { lineHeight: '56px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'body-md': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'label-sm': ['12px', { lineHeight: '14px', fontWeight: '600' }],
        'body-sm': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'label-md': ['14px', { lineHeight: '16px', letterSpacing: '0.02em', fontWeight: '500' }],
        'headline-md': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'headline-sm': ['20px', { lineHeight: '28px', fontWeight: '600' }]
      }
    }
  },
  plugins: [forms, containerQueries],
}
