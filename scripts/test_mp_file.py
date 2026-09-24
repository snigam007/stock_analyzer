import multiprocessing as mp

def square(x):
    return x * x

if __name__ == "__main__":
    with mp.Pool(processes=4) as p:
        res = p.map(square, [1, 2, 3, 4, 5])
        print("Multiprocessing from file succeeded:", res)
