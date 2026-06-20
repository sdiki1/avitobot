const express = require('express');
const router = express.Router();
const usersController = require('../controllers/usersController');

// Route for user registration
router.get('/register', usersController.register);

// Route for user login
router.get('/login', usersController.login);

// Route for user logout
router.get('/logout', usersController.logout);

// Route to update user details
router.get('/update/:userId', usersController.updateUser);

// Route to delete a user account
router.get('/delete/:userId', usersController.deleteUser);

// Route to fetch details of a specific user by their username
router.get('/:username', usersController.getUserDetails);

module.exports = router;
