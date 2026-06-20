const express = require('express');
const router = express.Router();
const subscriptionsController = require('../controllers/subscriptionsController');

// Route to fetch all active subscriptions
router.get('/', subscriptionsController.viewAllSubscriptions);

// Route to add a new subscription
router.get('/create', subscriptionsController.addSubscription);

// Route to update details of a specific subscription by its ID
router.get('/update/:subscriptionId', subscriptionsController.updateSubscription);

// Route to delete a specific subscription by its ID
router.get('/delete/:subscriptionId', subscriptionsController.deleteSubscription);

// Route to view details of a specific subscription by its ID
router.get('/:subscriptionId', subscriptionsController.viewSubscriptionById);

module.exports = router;
