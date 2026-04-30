
// Delete Button Functionality Fix
(function() {
    'use strict';
    
    // Enhanced delete functionality with better error handling
    window.deleteStudyEnhanced = async function(studyId, accessionNumber) {
        if (!studyId) {
            alert('Invalid study ID');
            return;
        }
        
        // Confirm deletion
        const confirmMessage = `Are you sure you want to delete study "${accessionNumber}"?\n\nThis action cannot be undone.`;
        if (!confirm(confirmMessage)) {
            return;
        }
        
        try {
            // Get CSRF token
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                             document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                             getCookie('csrftoken');
            
            if (!csrfToken) {
                throw new Error('CSRF token not found. Please refresh the page.');
            }
            
            // Find and disable delete button
            const deleteButton = document.querySelector(`button[onclick*="deleteStudy('${studyId}'"]`) ||
                                document.querySelector(`button[onclick*="deleteStudyEnhanced('${studyId}'"]`);
            
            if (deleteButton) {
                deleteButton.disabled = true;
                deleteButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';
            }
            
            // Make delete request
            const response = await fetch(`/worklist/api/study/${studyId}/delete/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'same-origin'
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}: Delete failed`);
            }
            
            // Success - remove from UI
            const row = document.querySelector(`tr[data-study-id="${studyId}"]`);
            if (row) {
                row.remove();
            }
            
            // Update any counters
            if (typeof updateStatusCounts === 'function') {
                updateStatusCounts();
            }
            
            // Show success message
            if (typeof showToast === 'function') {
                showToast(`Study ${accessionNumber} deleted successfully`, 'success');
            } else {
                alert(`Study ${accessionNumber} deleted successfully`);
            }
            
        } catch (error) {
            console.error('Delete failed:', error);
            
            // Reset button
            if (deleteButton) {
                deleteButton.disabled = false;
                deleteButton.innerHTML = '<i class="fas fa-trash"></i> DELETE';
            }
            
            // Show error
            if (typeof showToast === 'function') {
                showToast(`Failed to delete study: ${error.message}`, 'error');
            } else {
                alert(`Failed to delete study: ${error.message}`);
            }
        }
    };
    
    // Helper function to get cookie
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    // Override existing deleteStudy function
    window.deleteStudy = window.deleteStudyEnhanced;
    
})();
