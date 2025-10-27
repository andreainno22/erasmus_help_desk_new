// Gestisce la logica per login, registrazione e dashboard dell'università

document.addEventListener('DOMContentLoaded', () => {
    const pathname = window.location.pathname;

    if (pathname.endsWith('login.html')) {
        initLoginPage();
    } else if (pathname.endsWith('register.html')) {
        initRegisterPage();
    } else if (pathname.endsWith('dashboard.html')) {
        initDashboardPage();
    }
});

function initLoginPage() {
    const loginForm = document.getElementById('login-form');
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        
        try {
            const response = await fetch('/api/universities/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    institutional_email: email,
                    password: password
                })
            });

            if (response.ok) {
                const data = await response.json();
                localStorage.setItem('university_token', data.access_token);
                window.location.href = '/static/dashboard.html';
            } else {
                const errorData = await response.json();
                showError(errorData.detail || 'Login fallito');
            }
        } catch (error) {
            showError('Errore di connessione');
        }
    });
}

function initRegisterPage() {
    const registerForm = document.getElementById('register-form');
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('name').value;
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;

        try {
            const response = await fetch('/api/universities/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    university_name: name, 
                    institutional_email: email, 
                    password: password 
                })
            });

            if (response.ok) {
                // Redirect to login page after successful registration
                window.location.href = '/static/login.html';
            } else {
                const errorData = await response.json();
                showError(errorData.detail || 'Registrazione fallita');
            }
        } catch (error) {
            showError('Errore di connessione');
        }
    });
}

function initDashboardPage() {
    const token = localStorage.getItem('university_token');
    if (!token) {
        window.location.href = '/static/login.html';
        return;
    }

    const welcomeMessage = document.getElementById('welcome-message');
    const uploadForm = document.getElementById('upload-form');
    const documentsList = document.getElementById('documents-list');
    const uploadSpinner = document.getElementById('upload-spinner');

    // Fetch user profile
    fetch('/api/universities/profile', {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(response => {
        if (!response.ok) throw new Error('Token non valido');
        return response.json();
    })
    .then(data => {
        welcomeMessage.textContent = `Benvenuta, ${data.university_name}!`;
    })
    .catch(() => {
        localStorage.removeItem('university_token');
        window.location.href = '/static/login.html';
    });

    // Funzione per caricare e renderizzare i documenti
    async function fetchAndRenderDocuments() {
        try {
            const response = await fetch('/api/universities/documents', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await response.json();
            
            documentsList.innerHTML = ''; // Pulisce la lista
            
            if (data.documents && data.documents.length > 0) {
                data.documents.forEach(doc => {
                    const docElement = document.createElement('div');
                    docElement.className = 'document-item';
                    docElement.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:center">
                          <div><strong>${doc.original_filename}</strong><br/><small>${doc.document_type || 'N/A'} • ${doc.academic_year || 'N/A'}</small></div>
                          <div>
                            <button class="btn btn-danger btn-sm delete-btn" data-doc-id="${doc.id}">Elimina</button>
                          </div>
                        </div>
                    `;
                    documentsList.appendChild(docElement);
                });
            } else {
                documentsList.innerHTML = '<p class="text-muted">Nessun documento trovato.</p>';
            }
        } catch (error) {
            showError('Errore nel caricamento dei documenti.');
        }
    }

    // Gestione upload (singolo form per tre tipi di documento)
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        uploadSpinner.hidden = false;

        const docType = document.getElementById('doc-type').value;
        const file = document.getElementById('doc-file').files[0];
        const academicYear = document.getElementById('academic-year').value;

        if (!file) {
            showError('Seleziona un file da caricare');
            uploadSpinner.hidden = true;
            return;
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('academic_year', academicYear);

        let endpoint = '/api/universities/upload/erasmus-call';
        if (docType === 'destinazioni') endpoint = '/api/universities/upload/destinazioni';
        if (docType === 'corsi_erasmus') endpoint = '/api/universities/upload/erasmus-courses';

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });

            if (response.ok) {
                uploadForm.reset();
                await fetchAndRenderDocuments(); // Aggiorna la lista
            } else {
                const errorData = await response.json().catch(()=>({}));
                showError(errorData.detail || 'Upload fallito');
            }
        } catch (error) {
            showError('Errore di connessione durante l-upload.');
        } finally {
            uploadSpinner.hidden = true;
        }
    });

    // Gestione eliminazione (con event delegation)
    documentsList.addEventListener('click', async (e) => {
        if (e.target.classList.contains('delete-btn')) {
            const docId = e.target.dataset.docId;
            if (!confirm('Sei sicuro di voler eliminare questo documento?')) return;

            try {
                const response = await fetch(`/api/universities/documents/${docId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.ok) {
                    await fetchAndRenderDocuments(); // Aggiorna la lista
                } else {
                    const errorData = await response.json();
                    showError(errorData.detail || 'Eliminazione fallita');
                }
            } catch (error) {
                showError('Errore di connessione durante l-eliminazione.');
            }
        }
    });

    // Logout
    document.getElementById('logout_btn').addEventListener('click', () => {
        localStorage.removeItem('university_token');
        window.location.href = '/static/login.html';
    });

    // Caricamento iniziale dei documenti
    fetchAndRenderDocuments();
}

function showError(message) {
    const errorBox = document.getElementById('error-box');
    errorBox.textContent = message;
    errorBox.hidden = false;
}
