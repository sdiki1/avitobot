const express = require('express');
const router = express.Router();
const identityVerificationController = require('../controllers/identityVerificationController');

router.get('/submit', identityVerificationController.submitDocument);
router.get('/pending', identityVerificationController.viewPendingVerifications);
router.get('/verify/:documentId', identityVerificationController.verifyDocument);
router.get('/reject/:documentId', identityVerificationController.rejectDocument);

module.exports = router;
