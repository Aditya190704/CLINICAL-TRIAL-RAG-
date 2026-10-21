import React, { useState, useEffect } from "react";
import Modal from "../ui/Modal";
import Button from "../ui/Button";

/**
 * Modal to rename a session title.
 */
export default function RenameModal({
  isOpen,
  onClose,
  onSave,
  currentTitle = "",
}) {
  const [title, setTitle] = useState(currentTitle);

  useEffect(() => {
    setTitle(currentTitle);
  }, [currentTitle, isOpen]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (title.trim()) {
      onSave(title.trim());
      onClose();
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Rename Session"
      description="Enter a custom clinical or research title for this case."
    >
      <form onSubmit={handleSubmit} className="rename-form">
        <input
          type="text"
          className="rename-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Stage IIIB NSCLC - 62yo Female"
          autoFocus
          maxLength={80}
        />
        <div className="rename-actions">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={!title.trim()}>
            Save Title
          </Button>
        </div>
      </form>
    </Modal>
  );
}

