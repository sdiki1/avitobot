const express = require('express');
const router = express.Router();
const messagesController = require('../controllers/messagesController');

router.get('/', messagesController.viewAllMessages);
router.get('/send', messagesController.sendMessage);
router.get('/delete/:messageId', messagesController.deleteMessage);

module.exports = router;
