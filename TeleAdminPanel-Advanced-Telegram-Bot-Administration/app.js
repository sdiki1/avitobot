const express = require('express');
const path = require('path');
const webRoutes = require('./routes/web');

const app = express();
const PORT = Number(process.env.PORT || 3000);
const ADMIN_BASE_PATH = process.env.ADMIN_BASE_PATH || "/admin";

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use((req, res, next) => {
  res.locals.adminBase = ADMIN_BASE_PATH;
  next();
});

app.use((req, res, next) => {
  res.locals.currentPage = req.path.split('/')[1] || '';
  next();
});

app.use('/', webRoutes);

app.listen(PORT, () => {
  console.log(`Admin panel is running on port ${PORT}`);
});
