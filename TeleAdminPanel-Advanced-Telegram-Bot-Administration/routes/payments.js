const express = require('express');
const router = express.Router();
const paymentsController = require('../controllers/paymentsController');

router.get('/', paymentsController.viewAllPayments);
router.get('/create', paymentsController.createPayment);
router.get('/update/:paymentId', paymentsController.updatePayment);
router.get('/delete/:paymentId', paymentsController.deletePayment);

module.exports = router;
