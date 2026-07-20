C Numerical Methods Test Programs
=================================

Each C file is independent and contains one numerical method plus a main function that tests it.

Compile one program:

    gcc -std=c11 -Wall -Wextra -Wpedantic 12_bisection.c -lm -o 12_bisection

Compile all programs on Windows:

    build_all.bat

Files cover sum, mean, min/max, variance, standard deviation, dot product, vector norm, linspace, Horner polynomial evaluation, centered differentiation, trapezoidal integration, Simpson integration, bisection, Newton's method, and Gaussian elimination.
