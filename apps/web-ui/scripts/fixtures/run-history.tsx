import React from 'react';
import {createRoot} from 'react-dom/client';
import {ExportedReportsList} from '../../src/components/ExportedReportsList';
import '../../src/styles.css';
createRoot(document.getElementById('root')!).render(<ExportedReportsList/>);
